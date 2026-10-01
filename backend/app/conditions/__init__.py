"""匯入所有條件實作，觸發各自的 @register_condition 裝飾器，讓registry在app啟動時就填好。
新增條件時，記得把新檔案加進這裡，不然registry抓不到。"""

from app.conditions import (  # noqa: F401
    bollinger_band,
    ema_cross,
    kd_macd,
    volume_spike,
)
