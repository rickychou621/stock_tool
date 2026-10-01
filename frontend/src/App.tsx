import { BrowserRouter, Route, Routes } from 'react-router-dom'
import { Layout } from './components/Layout'
import { ScreeningPage } from './features/screening/ScreeningPage'
import { CandidatePoolPage } from './features/screening/CandidatePoolPage'
import { WatchlistPage } from './features/watchlist/WatchlistPage'
import { StockLookupPage } from './features/chart/StockLookupPage'
import { RulesPage } from './features/rules/RulesPage'
import { SettingsPage } from './features/settings/SettingsPage'

function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route element={<Layout />}>
          <Route index element={<WatchlistPage />} />
          <Route path="matches" element={<ScreeningPage />} />
          <Route path="candidates" element={<CandidatePoolPage />} />
          <Route path="watchlist" element={<WatchlistPage />} />
          <Route path="chart" element={<StockLookupPage />} />
          <Route path="rules" element={<RulesPage />} />
          <Route path="settings" element={<SettingsPage />} />
        </Route>
      </Routes>
    </BrowserRouter>
  )
}

export default App
