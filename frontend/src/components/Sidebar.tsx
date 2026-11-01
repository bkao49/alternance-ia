import type { Me } from "../api/types";
import { APP_NAME } from "../brand";
import { Logo } from "./Logo";

export type Page = "home" | "offers" | "criteria" | "profile";

export function Sidebar({ user, page, onSignOut }: { user: Me; page: Page; onSignOut: () => void }) {
  return (
    <aside className="side">
      <p className="brand">
        <Logo className="brand-logo" />
        <span className="brand-name">{APP_NAME}</span>
      </p>
      <nav aria-label="Navigation principale" className="side-nav">
        <a href="#accueil" aria-current={page === "home" ? "page" : undefined}>
          Accueil
        </a>
        <a href="#offres" aria-current={page === "offers" ? "page" : undefined}>
          Offres
        </a>
        <a href="#candidatures">Candidatures</a>
        <a href="#criteres" aria-current={page === "criteria" ? "page" : undefined}>
          Mes critères
        </a>
        <a href="#profil" aria-current={page === "profile" ? "page" : undefined}>
          Mon profil
        </a>
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
