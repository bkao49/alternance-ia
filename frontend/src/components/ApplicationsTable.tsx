import { useMemo, useState } from "react";

import type { Application, Status } from "../api/types";
import type { ScoresByOffer } from "../hooks";
import { formatDate } from "../format";
import { MoveSelect, Score, StatusBadge } from "./common";

type SortKey = "company" | "title" | "status" | "score" | "created_at";
type Sort = { key: SortKey; direction: "ascending" | "descending" };

const COLUMNS: [SortKey, string][] = [
  ["company", "Entreprise"],
  ["title", "Poste"],
  ["status", "Statut"],
  ["score", "Score"],
  ["created_at", "Ajoutée le"],
];

function compare(a: Application, b: Application, key: SortKey, scores: ScoresByOffer): number {
  // Sans score, une candidature passe après les autres en tri croissant (comme une valeur vide).
  if (key === "score") return scoreOf(a, scores) - scoreOf(b, scores);
  if (key === "status") return a.status.position - b.status.position;
  if (key === "created_at") return a.created_at.localeCompare(b.created_at);
  return (a[key] ?? "").localeCompare(b[key] ?? "", "fr", { sensitivity: "base" });
}

const scoreOf = (a: Application, scores: ScoresByOffer) => (a.offer_id ? (scores[a.offer_id] ?? -1) : -1);

type Props = {
  applications: Application[];
  scores: ScoresByOffer;
  statuses: Status[];
  onOpen: (application: Application) => void;
  onMove: (application: Application, statusId: string) => void;
};

export function ApplicationsTable({ applications, statuses, scores, onOpen, onMove }: Props) {
  const [sort, setSort] = useState<Sort>({ key: "created_at", direction: "descending" });

  const rows = useMemo(() => {
    const sorted = [...applications].sort((a, b) => compare(a, b, sort.key, scores));
    return sort.direction === "ascending" ? sorted : sorted.reverse();
  }, [applications, sort, scores]);

  function toggle(key: SortKey) {
    setSort((current) =>
      current.key === key
        ? { key, direction: current.direction === "ascending" ? "descending" : "ascending" }
        : { key, direction: "ascending" },
    );
  }

  if (applications.length === 0) return <p className="empty">Aucune candidature ne correspond à ces critères.</p>;

  return (
    <div className="table-wrap">
      <table>
        <caption className="visually-hidden">Candidatures</caption>
        <thead>
          <tr>
            {COLUMNS.map(([key, label]) => (
              <th key={key} scope="col" aria-sort={sort.key === key ? sort.direction : "none"}>
                <button type="button" className="sort" onClick={() => toggle(key)}>
                  {label}
                  <span aria-hidden="true">{sort.key === key ? (sort.direction === "ascending" ? " ▲" : " ▼") : ""}</span>
                </button>
              </th>
            ))}
            <th scope="col">Action</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((application) => (
            <tr key={application.id}>
              <th scope="row">
                <button type="button" className="link" onClick={() => onOpen(application)}>
                  {application.company}
                </button>
              </th>
              <td>{application.title}</td>
              <td>
                <StatusBadge status={application.status} />
              </td>
              <td>
                <Score value={application.offer_id ? scores[application.offer_id] : undefined} />
              </td>
              <td>{formatDate(application.created_at)}</td>
              <td>
                <MoveSelect
                  application={application}
                  statuses={statuses}
                  onMove={(statusId) => onMove(application, statusId)}
                />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
