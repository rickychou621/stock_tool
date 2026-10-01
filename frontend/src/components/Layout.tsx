import { NavLink, Outlet, useLocation } from 'react-router-dom'

const NAV_ITEMS = [
  { to: '/', label: '觀察清單' },
  { to: '/matches', label: '今日符合戰法清單' },
  { to: '/candidates', label: '候選池' },
  { to: '/chart', label: '個股查詢' },
  { to: '/rules', label: '規則管理' },
  { to: '/settings', label: '系統設定' },
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
              <span className="nav-dot" aria-hidden="true" />
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
