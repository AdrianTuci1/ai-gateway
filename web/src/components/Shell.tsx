import { useEffect, useRef, useState, type ReactNode } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";

import { Icon } from "./Icon";
import { ErrorBox } from "./ui";
import { useAsync } from "../hooks";
import { api, clearSession, getEmail, getWorkspace, type Inventory } from "../api";

export type Crumb = { label: string; to?: string };
export type Command = {
  label: string;
  icon: string;
  onClick?: () => void;
  disabled?: boolean;
  primary?: boolean;
};
export type Tab = {
  label: string;
  to: string;
  count?: number;
  onClick?: () => void;
  status?: "error";
};

type NavItem = { label: string; to: string; icon: string; count?: number };
type NavSection = { section: string; items: NavItem[] };

type Props = {
  title: string;
  suffix?: string;
  subtitle?: string;
  icon?: string;
  crumbs?: Crumb[];
  commands?: Command[];
  tabs?: Tab[];
  activeTab?: string;
  children: ReactNode;
  onClose?: () => void;
  wide?: boolean;
  plain?: boolean;
  footer?: ReactNode;
};

export function Shell({
  title,
  suffix,
  subtitle,
  icon = "grid",
  crumbs = [],
  commands = [],
  tabs = [],
  activeTab,
  children,
  onClose,
  wide,
  plain,
  footer,
}: Props) {
  const workspace = getWorkspace();
  const location = useLocation();
  const navigate = useNavigate();
  const [menuOpen, setMenuOpen] = useState(false);
  const [navOpen, setNavOpen] = useState(false);
  const [collapsed, setCollapsed] = useState(
    () => localStorage.getItem("agw.nav-collapsed") === "1",
  );
  const accountRef = useRef<HTMLDivElement>(null);

  const toggleCollapsed = () => {
    setCollapsed((current) => {
      const next = !current;
      localStorage.setItem("agw.nav-collapsed", next ? "1" : "0");
      return next;
    });
  };

  useEffect(() => {
    setNavOpen(false);
  }, [location.pathname, location.search]);

  useEffect(() => {
    if (!menuOpen) return;
    const close = (event: MouseEvent) => {
      if (!accountRef.current?.contains(event.target as Node)) setMenuOpen(false);
    };
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, [menuOpen]);

  const inventory = useAsync<Inventory | null>(
    () =>
      workspace
        ? api<Inventory>(`/v1/workspaces/${workspace}/inventory`).catch(() => null)
        : Promise.resolve(null),
    [workspace],
  );
  const counts = inventory.data?.counts;

  const home: NavItem = { label: "Home", to: "/", icon: "home" };
  const sections: NavSection[] = [
    {
      section: "Resources",
      items: [
        {
          label: "All resources",
          to: "/resources",
          icon: "grid",
          count: counts ? counts.services + counts.agents : undefined,
        },
        { label: "Resource groups", to: "/groups", icon: "layers", count: counts?.groups },
        { label: "Agents", to: "/resources?type=agent", icon: "agent", count: counts?.agents },
        { label: "Services", to: "/resources?type=service", icon: "server", count: counts?.services },
      ],
    },
    {
      section: "Access",
      items: [
        { label: "Identities", to: "/identities", icon: "users" },
        { label: "Policies & grants", to: "/grants", icon: "shield" },
      ],
    },
    {
      section: "Observability",
      items: [
        { label: "Tracing", to: "/tracing", icon: "trace" },
        { label: "Audit log", to: "/audit", icon: "audit" },
      ],
    },
  ];

  return (
    <>
      <header className="topbar">
        <button
          className="topbar__menu-btn"
          type="button"
          aria-label={navOpen ? "Close navigation" : "Open navigation"}
          aria-expanded={navOpen}
          onClick={() => setNavOpen((open) => !open)}
        >
          <Icon name={navOpen ? "close" : "menu"} />
        </button>
        <div className="topbar__brand">
          <span className="topbar__mark">AG</span>
          AI Gateway
        </div>
        <button
          className="topbar__collapse"
          type="button"
          aria-label={collapsed ? "Expand navigation" : "Collapse navigation"}
          aria-expanded={!collapsed}
          title={collapsed ? "Expand navigation" : "Collapse navigation"}
          onClick={toggleCollapsed}
        >
          <Icon name="panel" size={16} />
        </button>
        <form
          className="topbar__search"
          onSubmit={(event) => {
            event.preventDefault();
            const value = new FormData(event.currentTarget).get("q");
            if (typeof value === "string" && value.trim()) {
              navigate(`/resources?q=${encodeURIComponent(value.trim())}`);
            }
          }}
        >
          <Icon name="search" size={14} />
          <input name="q" placeholder="Search resources, services and docs (/) " />
        </form>
        <div className="topbar__spacer" />
        <button className="topbar__action" type="button" title="Notifications">
          <Icon name="alert" />
        </button>
        <button className="topbar__action" type="button" title="Settings">
          <Icon name="settings" />
        </button>
        <div className="topbar__account" ref={accountRef}>
          <button
            className="topbar__user"
            type="button"
            title="Account"
            onClick={() => setMenuOpen((open) => !open)}
          >
            <span className="topbar__user-icon">
              <Icon name="agent" size={16} />
            </span>
            <strong>{getEmail() || "signed in"}</strong>
            <span>{workspace}</span>
          </button>
          {menuOpen ? (
            <div className="account-menu">
              <div className="account-menu__head">
                <strong>{getEmail() || "Signed in"}</strong>
                <span className="muted small">{workspace}</span>
              </div>
              <button
                type="button"
                onClick={() => {
                  clearSession();
                  navigate("/", { replace: true });
                  window.location.reload();
                }}
              >
                <Icon name="key" size={14} />
                Sign out
              </button>
            </div>
          ) : null}
        </div>
      </header>
      <div className={`shell${collapsed ? " shell--collapsed" : ""}`}>
        {navOpen ? (
          <button
            className="sidenav-backdrop"
            type="button"
            aria-label="Close navigation"
            onClick={() => setNavOpen(false)}
          />
        ) : null}
        <nav
          className={`sidenav${navOpen ? " is-open" : ""}${
            collapsed && !navOpen ? " sidenav--collapsed" : ""
          }`}
          aria-label="Main"
        >
          <div className="sidenav__header">
            <span className="sidenav__title">Navigation</span>
            <button
              className="sidenav__collapse"
              type="button"
              aria-label={collapsed ? "Expand navigation" : "Collapse navigation"}
              aria-expanded={!collapsed}
              title={collapsed ? "Expand navigation" : "Collapse navigation"}
              onClick={toggleCollapsed}
            >
              <Icon name="panel" size={14} />
              <span>{collapsed ? "Expand" : "Collapse"}</span>
            </button>
          </div>
          <SideLink item={home} path={location.pathname + location.search} />
          {sections.map((section) => (
            <div className="sidenav__group" key={section.section}>
              <div className="sidenav__label">{section.section}</div>
              {section.items.map((item) => (
                <SideLink
                  key={item.to}
                  item={item}
                  path={location.pathname + location.search}
                />
              ))}
            </div>
          ))}
        </nav>
        <main className="main">
          <nav className="breadcrumbs" aria-label="Breadcrumb">
            <Link to="/">Home</Link>
            {crumbs.map((crumb) => (
              <span key={crumb.label} className="row" style={{ gap: 8 }}>
                <span className="breadcrumbs__sep">›</span>
                {crumb.to ? <Link to={crumb.to}>{crumb.label}</Link> : <span>{crumb.label}</span>}
              </span>
            ))}
          </nav>
          <div className={`page-header${plain ? " page-header--plain" : ""}`}>
            {plain ? null : (
              <div className="page-header__icon">
                <Icon name={icon} size={20} />
              </div>
            )}
            <div className="page-header__text">
              <h1>
                {title}
                {suffix ? <span className="page-header__suffix"> | {suffix}</span> : null}
              </h1>
              {subtitle ? <div className="page-header__subtitle">{subtitle}</div> : null}
            </div>
            <button
              className="page-header__close"
              type="button"
              aria-label="Close"
              onClick={onClose ?? (() => window.history.back())}
            >
              <Icon name="close" />
            </button>
          </div>
          {commands.length > 0 ? (
            <div className="command-bar">
              {commands.map((command) => (
                <button
                  key={command.label}
                  className={command.primary ? "btn btn--primary" : "command-bar__item"}
                  type="button"
                  onClick={command.onClick}
                  disabled={command.disabled}
                >
                  <Icon name={command.icon} size={14} />
                  {command.label}
                </button>
              ))}
            </div>
          ) : null}
          {tabs.length > 0 ? (
            <div className="tabs" role="tablist">
              {tabs.map((tab) => {
                const className = `tab${activeTab === tab.to ? " is-active" : ""}`;
                const content = (
                  <>
                    {tab.status === "error" ? (
                      <span className="tab__error" aria-label="Needs attention">
                        <Icon name="close" size={12} />
                      </span>
                    ) : null}
                    {tab.label}
                    {tab.count !== undefined ? (
                      <span className="tab__count">{tab.count}</span>
                    ) : null}
                  </>
                );
                return tab.onClick ? (
                  <button
                    key={tab.to}
                    type="button"
                    role="tab"
                    aria-selected={activeTab === tab.to}
                    className={className}
                    onClick={tab.onClick}
                  >
                    {content}
                  </button>
                ) : (
                  <Link
                    key={tab.to}
                    to={tab.to}
                    role="tab"
                    aria-selected={activeTab === tab.to}
                    className={className}
                  >
                    {content}
                  </Link>
                );
              })}
            </div>
          ) : null}
          <div className={`content${wide ? " content--flush" : ""}`}>
            {inventory.error ? (
              <ErrorBox error={inventory.error} onRetry={inventory.reload} />
            ) : null}
            {children}
          </div>
          {footer ? <footer className="form-footer">{footer}</footer> : null}
        </main>
      </div>
    </>
  );
}

function SideLink({ item, path }: { item: NavItem; path: string }) {
  const base = item.to.split("?")[0];
  const active =
    path === item.to ||
    (item.to !== "/" && !item.to.includes("?") && path.startsWith(base));
  return (
    <Link
      to={item.to}
      className={`sidenav__link${active ? " is-active" : ""}`}
      title={item.label}
    >
      <Icon name={item.icon} size={14} />
      <span className="truncate">{item.label}</span>
      {item.count !== undefined ? <span className="sidenav__count">{item.count}</span> : null}
    </Link>
  );
}
