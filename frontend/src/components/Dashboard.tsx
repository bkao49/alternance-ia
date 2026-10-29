import { useMemo, useState } from "react";

import { unwrap } from "../api/client";
import { useApi } from "../api/context";
import type { Application, Me } from "../api/types";
import { useDashboardData } from "../hooks";
import { ApplicationDialog } from "./ApplicationDialog";
import { ApplicationsTable } from "./ApplicationsTable";
import { KanbanBoard } from "./KanbanBoard";
import { NewApplicationDialog, type NewApplication } from "./NewApplicationDialog";
import { StatsStrip } from "./StatsStrip";

type View = "table" | "kanban";

export function Dashboard({ user, onLogout }: { user: Me; onLogout: () => void }) {
  const api = useApi();
  const { state, reload } = useDashboardData();
  const [view, setView] = useState<View>("table");
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const [announcement, setAnnouncement] = useState("");

  const applications = useMemo(() => (state.phase === "ready" ? state.applications : []), [state]);
  const visible = useMemo(() => {
    const needle = search.trim().toLowerCase();
    return applications.filter(
      (a) =>
        (!statusFilter || a.status.id === statusFilter) &&
        (!needle || `${a.company ?? ""} ${a.title ?? ""}`.toLowerCase().includes(needle)),
    );
  }, [applications, search, statusFilter]);

  async function run(action: () => Promise<unknown>, message: string) {
    try {
      await action();
      await reload();
      setProblem(null);
      setAnnouncement(message);
    } catch (failure) {
      setProblem(failure instanceof Error ? failure.message : "Action impossible");
    }
  }

  const move = (application: Application, statusId: string) =>
    run(
      async () =>
        unwrap(
          await api.POST("/applications/{applicationId}/status", {
            params: { path: { applicationId: application.id } },
            body: { status_id: statusId },
          }),
        ),
      `${application.company} déplacée`,
    );

  const confirmSent = (application: Application) =>
    run(
      async () =>
        unwrap(
          await api.POST("/applications/{applicationId}/confirm-sent", {
            params: { path: { applicationId: application.id } },
            body: { confirmed: true },
          }),
        ),
      `${application.company} marquée comme envoyée`,
    );

  const create = (body: NewApplication) =>
    run(async () => unwrap(await api.POST("/applications", { body })), `${body.company} ajoutée`);

  const selected = applications.find((a) => a.id === selectedId) ?? null;

  return (
    <div className="shell">
      <header className="topbar">
        <h1>Suivi d'alternance</h1>
        <div className="topbar-actions">
          <button type="button" className="primary" onClick={() => setCreating(true)}>
            Nouvelle candidature
          </button>
          <span className="muted who">{user.email}</span>
          <button type="button" onClick={onLogout}>
            Se déconnecter
          </button>
        </div>
      </header>

      <main>
        {state.phase === "loading" && <p role="status">Chargement…</p>}
        {state.phase === "error" && (
          <p role="alert" className="error">
            {state.message}{" "}
            <button type="button" onClick={() => void reload()}>
              Réessayer
            </button>
          </p>
        )}

        {state.phase === "ready" && (
          <>
            <StatsStrip stats={state.stats} />

            <section aria-labelledby="applications-title" className="card">
              <div className="toolbar">
                <h2 id="applications-title">Candidatures</h2>
                <div className="filters">
                  <input
                    type="search"
                    aria-label="Rechercher une candidature"
                    placeholder="Rechercher…"
                    value={search}
                    onChange={(e) => setSearch(e.target.value)}
                  />
                  <select aria-label="Filtrer par statut" value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)}>
                    <option value="">Tous les statuts</option>
                    {state.statuses.map((status) => (
                      <option key={status.id} value={status.id}>
                        {status.name}
                      </option>
                    ))}
                  </select>
                  <div className="segmented" role="group" aria-label="Affichage">
                    <button type="button" aria-pressed={view === "table"} onClick={() => setView("table")}>
                      Tableau
                    </button>
                    <button type="button" aria-pressed={view === "kanban"} onClick={() => setView("kanban")}>
                      Kanban
                    </button>
                  </div>
                </div>
              </div>

              {problem && (
                <p role="alert" className="error">
                  {problem}
                </p>
              )}

              {view === "table" ? (
                <ApplicationsTable
                  applications={visible}
                  statuses={state.statuses}
                  onOpen={(a) => setSelectedId(a.id)}
                  onMove={move}
                />
              ) : (
                <KanbanBoard
                  applications={visible}
                  statuses={state.statuses}
                  onOpen={(a) => setSelectedId(a.id)}
                  onMove={move}
                />
              )}
            </section>
          </>
        )}
      </main>

      <p className="visually-hidden" role="status" aria-live="polite">
        {announcement}
      </p>

      {selected && state.phase === "ready" && (
        <ApplicationDialog
          application={selected}
          statuses={state.statuses}
          onMove={(statusId) => void move(selected, statusId)}
          onConfirmSent={() => confirmSent(selected)}
          onClose={() => setSelectedId(null)}
        />
      )}
      {creating && <NewApplicationDialog onCreate={create} onClose={() => setCreating(false)} />}
    </div>
  );
}
