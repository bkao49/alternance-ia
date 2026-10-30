import type { Me } from "../api/types";
import { APP_NAME } from "../brand";
import { Logo } from "./Logo";

export type Page = "home" | "applications";

type Props = { user: Me; page: Page; onNavigate: (page: Page) => void; onSignOut: () => void };

export function Sidebar({ user, page, onNavigate, onSignOut }: Props) {
  return (
    <aside className="side">
      <p className="brand">
        <Logo className="brand-logo" />
        <span className="brand-name">{APP_NAME}</span>
      </p>
      <nav aria-label="Navigation principale" className="side-nav">
        <button type="button" aria-current={page === "home" ? "page" : undefined} onClick={() => onNavigate("home")}>
          Accueil
        </button>
        {/* Pas encore d'écran des offres : l'entrée reste visible, inactive, et le dit. */}
        <span className="side-soon" aria-disabled="true">
          Offres <span className="chip">bientôt</span>
        </span>
        <button
          type="button"
          aria-current={page === "applications" ? "page" : undefined}
          onClick={() => onNavigate("applications")}
        >
          Candidatures
        </button>
      </nav>
      <div className="side-me">
        <span className="side-email">{user.email}</span>
        <button type="button" className="link" onClick={onSignOut}>
          Se déconnecter
        </button>
      </div>
    </aside>
  );
}
