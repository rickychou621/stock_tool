// 股票代號對照名稱的共用清單。之後接上後端 market_data 的 Stock 表後，
// 這個檔案可以整個移除，改用API回傳的資料(通常回應本身就會直接帶name欄位)。
export interface StockInfo {
  ticker: string
  name: string
}

export const STOCK_DIRECTORY: StockInfo[] = [
  { ticker: '2330', name: '台積電' },
  { ticker: '2317', name: '鴻海' },
  { ticker: '2454', name: '聯發科' },
  { ticker: '2308', name: '台達電' },
  { ticker: '3034', name: '聯詠' },
  { ticker: '2412', name: '中華電' },
  { ticker: '2603', name: '長榮' },
  { ticker: '3711', name: '日月光投控' },
  { ticker: '3481', name: '群創' },
  { ticker: '2409', name: '友達' },
  { ticker: '6182', name: '合晶' },
  { ticker: '3532', name: '台勝科' },
  { ticker: '6488', name: '環球晶' },
  { ticker: '3016', name: '嘉晶' },
  { ticker: '3105', name: '穩懋' },
  { ticker: '2455', name: '全新' },
  { ticker: '8086', name: '宏捷科' },
  { ticker: '6274', name: '台燿' },
  { ticker: '6213', name: '聯茂' },
  { ticker: '2383', name: '台光電' },
  { ticker: '3026', name: '禾伸堂' },
  { ticker: '6173', name: '信昌電' },
  { ticker: '3037', name: '欣興' },
  { ticker: '3189', name: '景碩' },
  { ticker: '8046', name: '南電' },
]

const directoryMap = new Map(STOCK_DIRECTORY.map((s) => [s.ticker, s.name]))

export function getStockName(ticker: string): string {
  return directoryMap.get(ticker) ?? '—'
}
