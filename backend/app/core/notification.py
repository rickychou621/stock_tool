"""Line-preserving pagination for Telegram summaries."""

from app.alerts.notification import MESSAGE_LIMIT, _text_size


def _pages(lines, *, title="全市場掃描結果"):
    # Reserve enough room for every possible continuation heading before packing.
    reserve = _text_size(f"{title}（續 {len(lines)}/{len(lines)}）\n")
    pages, current, size = [], [], 0
    for line in lines:
        added = _text_size(line) + bool(current)
        if current and size + added > MESSAGE_LIMIT - (reserve if pages else 0):
            pages.append("\n".join(current))
            current, size = [], 0
        current.append(line)
        size += _text_size(line) + (len(current) > 1)
    if current:
        pages.append("\n".join(current))
    return [
        page if i == 1 else f"{title}（續 {i}/{len(pages)}）\n{page}"
        for i, page in enumerate(pages, 1)
    ]
