import { FontAwesomeIcon } from '@fortawesome/react-fontawesome'
import {
  faBolt,
  faChartLine,
  faEye,
  faFlask,
  faGear,
  faGlobe,
  faInbox,
  faSliders,
} from '@fortawesome/free-solid-svg-icons'
import { NavLink, Outlet, useLocation } from 'react-router-dom'

const NAV_ITEMS = [
  { to: '/', label: '觀察清單', icon: faEye },
  { to: '/market-scan', label: '全市場掃描', icon: faGlobe },
  { to: '/matches', label: '今日符合戰法清單', icon: faBolt },
  { to: '/candidates', label: '候選池', icon: faInbox },
  { to: '/chart', label: '個股查詢', icon: faChartLine },
  { to: '/backtest', label: '戰法回測', icon: faFlask },
  { to: '/rules', label: '規則管理', icon: faSliders },
  { to: '/settings', label: '系統設定', icon: faGear },
]

export function Layout() {
  const { pathname } = useLocation()
  return (
    <div className="app-shell">
      <header className="app-header">
        <div className="app-brand">
          <span className="brand-mark" aria-hidden="true">
            ▥
          </span>
          <div>
            <span className="app-title">股票告警系統</span>
            <small>追蹤・篩選・判斷</small>
          </div>
        </div>
        <span className="nav-caption">工作空間</span>
        <nav className="app-nav" aria-label="主要導覽">
          {NAV_ITEMS.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.to === '/'}
              className={({ isActive }) =>
                isActive || (item.to === '/' && pathname === '/watchlist')
                  ? 'app-nav__link is-active'
                  : 'app-nav__link'
              }
            >
              <FontAwesomeIcon icon={item.icon} className="nav-icon" />
              {item.label}
            </NavLink>
          ))}
        </nav>
      </header>
      <main className="app-content">
        <Outlet />
      </main>
    </div>
  )
}
