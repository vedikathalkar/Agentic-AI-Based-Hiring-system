import { useCallback, useEffect, useRef, useState } from 'react';
import { Link, NavLink, useLocation, useNavigate } from 'react-router-dom';
import { Bell, ChevronDown, Coins, LayoutDashboard, LifeBuoy, LogOut, Menu, Moon, ChevronsLeft, ChevronsRight, Settings, Sun, User, X } from 'lucide-react';
import Logo from './Logo';
import { NAV, HOME, PROFILE_PATH, SETTINGS_PATH, LOGIN_PATH } from './navConfig';
import { useApp } from '../context/AppContext';
import { api } from '../api';

function timeAgo(value) {
  if (!value) return '';
  const iso = /Z|[+-]\d\d:?\d\d$/.test(value) ? value : `${value}Z`;
  const s = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000);
  if (s < 60) return 'just now';
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
  return `${Math.floor(s / 86400)}d ago`;
}

export function ThemeToggle({ compact }) {
  const { theme, setTheme } = useApp();
  const dark = theme === 'dark';
  return (
    <button className={compact ? 'icon-btn' : 'menu-item'} onClick={() => setTheme(dark ? 'light' : 'dark')}
            aria-label={`Switch to ${dark ? 'light' : 'dark'} mode`} title={`Switch to ${dark ? 'light' : 'dark'} mode`}>
      {dark ? <Sun size={18} aria-hidden="true" /> : <Moon size={18} aria-hidden="true" />}
      {!compact && <span>{dark ? 'Light Mode' : 'Dark Mode'}</span>}
    </button>
  );
}

function useOutside(ref, onOutside, active) {
  useEffect(() => {
    if (!active) return undefined;
    const h = (e) => { if (ref.current && !ref.current.contains(e.target)) onOutside(); };
    const k = (e) => { if (e.key === 'Escape') onOutside(); };
    document.addEventListener('mousedown', h);
    document.addEventListener('keydown', k);
    return () => { document.removeEventListener('mousedown', h); document.removeEventListener('keydown', k); };
  }, [ref, onOutside, active]);
}

function NotificationBell() {
  const navigate = useNavigate();
  const [open, setOpen] = useState(false);
  const [data, setData] = useState({ unread: 0, items: [] });
  const [error, setError] = useState(null);
  const ref = useRef(null);
  const close = useCallback(() => setOpen(false), []);
  useOutside(ref, close, open);

  const load = useCallback(async (full) => {
    try {
      if (full) setData(await api.getNotifications({ limit: 15 }));
      else { const { unread } = await api.unreadCount(); setData((d) => ({ ...d, unread })); }
      setError(null);
    } catch (e) { setError(e); }
  }, []);

  useEffect(() => {
    load(false);
    const id = setInterval(() => load(false), 60_000);
    return () => clearInterval(id);
  }, [load]);
  useEffect(() => { if (open) load(true); }, [open, load]);

  const openItem = async (n) => {
    if (!n.read) { try { await api.markNotificationRead(n.notification_id); } catch { /* ignore */ } }
    setOpen(false);
    load(true);
    if (n.link) navigate(n.link);
  };

  return (
    <div className="dropdown" ref={ref}>
      <button className="icon-btn" onClick={() => setOpen((o) => !o)} aria-haspopup="true" aria-expanded={open}
              aria-label={`Notifications${data.unread ? `, ${data.unread} unread` : ''}`}>
        <Bell size={19} aria-hidden="true" />
        {data.unread > 0 && <span className="badge-dot">{data.unread > 9 ? '9+' : data.unread}</span>}
      </button>
      {open && (
        <div className="dropdown-panel notif-panel" role="menu">
          <div className="row" style={{ padding: '10px 14px', borderBottom: '1px solid var(--ink-100)' }}>
            <b>Notifications</b><span className="spacer" />
            {data.unread > 0 && <button className="link-btn small" onClick={async () => { await api.markAllNotificationsRead(); load(true); }}>Mark all read</button>}
          </div>
          {error && <p className="small tone-danger" style={{ padding: 14 }}>Couldn't load notifications. <button className="link-btn" onClick={() => load(true)}>Retry</button></p>}
          {!error && data.items.length === 0 && <p className="small muted" style={{ padding: 18, textAlign: 'center' }}>You're all caught up.</p>}
          <ul className="notif-list">
            {data.items.map((n) => (
              <li key={n.notification_id}>
                <button className={`notif-item${n.read ? '' : ' unread'}`} onClick={() => openItem(n)}>
                  <b>{n.title}</b>
                  {n.message && <span className="small muted">{n.message}</span>}
                  <span className="small muted">{timeAgo(n.created_at)}</span>
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

function ProfileMenu() {
  const { user, logout } = useApp();
  const navigate = useNavigate();
  const [open, setOpen] = useState(false);
  const ref = useRef(null);
  const close = useCallback(() => setOpen(false), []);
  useOutside(ref, close, open);
  const role = user?.role || 'candidate';
  const initials = (user?.name || 'U').split(' ').map((n) => n[0]).join('').slice(0, 2).toUpperCase();
  const go = (path) => { setOpen(false); navigate(path); };
  const signOut = async () => { setOpen(false); await logout(); navigate(LOGIN_PATH[role] || '/'); };
  const roleLabel = { candidate: 'Candidate Account', hr: 'Hr Account', admin: 'Administrator' }[role];
  return (
    <div className="dropdown" ref={ref}>
      <button className="avatar-btn" onClick={() => setOpen((o) => !o)} aria-haspopup="true" aria-expanded={open} aria-label="Account menu">
        <span className="avatar" style={{ width: 36, height: 36, fontSize: 13 }}>{initials}</span>
        <ChevronDown size={14} aria-hidden="true" />
      </button>
      {open && (
        <div className="dropdown-panel profile-panel" role="menu">
          <div style={{ padding: '14px 16px', borderBottom: '1px solid var(--ink-100)' }}>
            <b>👋 Hey {user?.name || 'there'}!</b>
            <p className="small muted">{roleLabel}</p>
          </div>
          <button className="menu-item" role="menuitem" onClick={() => go(HOME[role])}><LayoutDashboard size={18} aria-hidden="true" /><span>Go to your dashboard</span></button>
          <button className="menu-item" role="menuitem" onClick={() => go(PROFILE_PATH[role])}><User size={18} aria-hidden="true" /><span>Profile</span></button>
          <button className="menu-item" role="menuitem" onClick={() => go(SETTINGS_PATH[role])}><Settings size={18} aria-hidden="true" /><span>Settings</span></button>
          <ThemeToggle />
          <div style={{ borderTop: '1px solid var(--ink-100)' }} />
          <button className="menu-item tone-danger" role="menuitem" onClick={signOut}><LogOut size={18} aria-hidden="true" /><span>Logout</span></button>
        </div>
      )}
    </div>
  );
}

function Sidebar({ role, collapsed, mobileOpen, onClose, onToggleCollapse }) {
  const { user, me, logout } = useApp();
  const navigate = useNavigate();
  const [closedGroups, setClosedGroups] = useState({});
  const groups = NAV[role] || [];
  const signOut = async () => { await logout(); navigate(LOGIN_PATH[role] || '/'); };
  const subtitle = role === 'hr'
    ? ({ verified: 'Verified employer', pending: 'Verification pending', rejected: 'Verification rejected' }[me?.verification_status] || 'Unverified')
    : role === 'admin' ? 'Admin console' : 'Candidate';
  return (
    <>
      {mobileOpen && <div className="side-scrim" onClick={onClose} aria-hidden="true" />}
      <aside className={`app-sidebar${collapsed ? ' collapsed' : ''}${mobileOpen ? ' open' : ''}`} aria-label="Main navigation">
        <div className="side-brand">
          <Link to={HOME[role]} onClick={onClose}><Logo tone="light" size={26} /></Link>
          <button className="icon-btn side-close" onClick={onClose} aria-label="Close menu"><X size={18} /></button>
        </div>
        <div className="side-account">
          <span className="avatar" style={{ width: 30, height: 30, fontSize: 11 }}>{(user?.name || 'U').slice(0, 1).toUpperCase()}</span>
          <div className="side-account-text"><b>{role === 'hr' ? 'HR Dashboard' : role === 'admin' ? 'Admin' : user?.name}</b><span>{subtitle}</span></div>
        </div>
        <nav className="side-nav">
          {groups.map((g, gi) => (
            <div key={g.title || gi} className="side-group">
              {g.title && (
                <button className="side-group-title" onClick={() => setClosedGroups((c) => ({ ...c, [g.title]: !c[g.title] }))} aria-expanded={!closedGroups[g.title]}>
                  <span>{g.title}</span><ChevronDown size={14} aria-hidden="true" style={{ transform: closedGroups[g.title] ? 'rotate(-90deg)' : 'none' }} />
                </button>
              )}
              {!closedGroups[g.title] && g.items.map(({ to, label, icon: Icon, end }) => (
                <NavLink key={to} to={to} end={end} onClick={onClose} title={collapsed ? label : undefined}
                         className={({ isActive }) => `hr-nav-link${isActive ? ' active' : ''}`}>
                  <Icon size={18} aria-hidden="true" /><span className="nav-text">{label}</span>
                </NavLink>
              ))}
            </div>
          ))}
          <button className="hr-nav-link" onClick={signOut}><LogOut size={18} aria-hidden="true" /><span className="nav-text">Logout</span></button>
        </nav>
        <button className="hr-nav-link side-collapse" onClick={onToggleCollapse} aria-label={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}>
          {collapsed ? <ChevronsRight size={18} /> : <ChevronsLeft size={18} />}<span className="nav-text">Collapse</span>
        </button>
      </aside>
    </>
  );
}

export default function AppShell({ role, children, wide }) {
  const { me } = useApp();
  const location = useLocation();
  const navigate = useNavigate();
  const [mobileOpen, setMobileOpen] = useState(false);
  const [collapsed, setCollapsed] = useState(() => { try { return localStorage.getItem('hirelune_sidebar') === 'collapsed'; } catch { return false; } });
  useEffect(() => { setMobileOpen(false); }, [location.pathname]);
  const toggleCollapse = () => setCollapsed((c) => { const n = !c; try { localStorage.setItem('hirelune_sidebar', n ? 'collapsed' : 'open'); } catch { /* ignore */ } return n; });
  const creditsPath = role === 'hr' ? '/hr/credits' : '/refer';
  return (
    <div className={`app-layout${collapsed ? ' is-collapsed' : ''}`}>
      <a href="#main" className="skip-link">Skip to content</a>
      <Sidebar role={role} collapsed={collapsed} mobileOpen={mobileOpen} onClose={() => setMobileOpen(false)} onToggleCollapse={toggleCollapse} />
      <div className="app-main-col">
        <header className="topbar">
          <button className="icon-btn topbar-menu" onClick={() => setMobileOpen(true)} aria-label="Open menu"><Menu size={20} /></button>
          <span className="spacer" />
          {role !== 'admin' && me?.credits !== undefined && (
            <button className="chip-btn" onClick={() => navigate(creditsPath)} title="Credits balance">
              <Coins size={16} aria-hidden="true" /> <b>{Number(me.credits).toLocaleString()}</b> <span className="hide-sm">credits</span>
            </button>
          )}
          {role !== 'admin' && (
            <button className="chip-btn hide-sm" onClick={() => navigate(role === 'hr' ? '/hr/support' : '/support')}><LifeBuoy size={16} aria-hidden="true" /> Support</button>
          )}
          <NotificationBell />
          <ThemeToggle compact />
          <ProfileMenu />
        </header>
        <main id="main" className={`app-main${wide ? ' wide' : ''}`}>{children}</main>
      </div>
    </div>
  );
}
