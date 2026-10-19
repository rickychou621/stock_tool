"""One short transaction swaps the published set, metadata and terminal task state."""

from sqlalchemy import delete, select

from app.market_scan.models import CandidateIndicator, ScanCandidate, ScanPublication, ScanTask


def publish(db, batch_id, outcomes, metadata):
    old = list(db.scalars(select(ScanCandidate)))
    by_ticker = {o.ticker: o for o in outcomes}
    selected = {r["id"] for r in metadata["rules"]}
    remove = []
    for row in old:
        outcome = by_ticker.get(row.ticker)
        if outcome is None:
            # No longer in the active exchange universe: retain as abnormal, never normal.
            row.status, row.status_reason = "stale", "標的已不在有效上市名單"
            continue
        status, reason = outcome.rules.get(row.rule_id, ("stale", "本次未成功評估"))
        if status == "normal" or (row.rule_id not in selected and outcome.succeeded):
            remove.append(row.id)
        else:
            row.status, row.status_reason = status, reason
    if remove:
        db.execute(delete(CandidateIndicator).where(CandidateIndicator.candidate_id.in_(remove)))
        db.execute(delete(ScanCandidate).where(ScanCandidate.id.in_(remove)))
    for outcome in outcomes:
        for values in outcome.candidates:
            candidate = ScanCandidate(**values, batch_id=batch_id)
            db.add(candidate)
            db.flush()
            db.add_all(
                [
                    CandidateIndicator(candidate_id=candidate.id, name=k, value=v)
                    for k, v in values["indicators"].items()
                ]
            )
    from app.market_scan.signal_tracking import record_signals

    record_signals(db, batch_id, outcomes, metadata)
    db.flush()
    statuses = list(db.scalars(select(ScanCandidate.status)))
    metadata = dict(
        metadata,
        normalCount=statuses.count("normal"),
        continuing=sum(o.continuing for o in outcomes),
        abnormalCount=sum(s != "normal" for s in statuses),
    )
    db.merge(ScanPublication(id=1, metadata_json=metadata))
    task = db.get(ScanTask, "scan")
    if task.batch_id != batch_id or task.status != "running":
        raise ValueError("任務所有權已變更，未發佈")
    task.status = metadata["status"]
    from datetime import datetime

    task.finished_at = datetime.fromisoformat(metadata["finishedAt"].removesuffix("Z"))
    db.commit()
