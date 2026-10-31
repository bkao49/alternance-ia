import { useCallback, useEffect, useRef, useState } from "react";

import { unwrap, type Api } from "../api/client";
import { useApi } from "../api/context";
import type { ContractType, Offer } from "../api/types";
import { Score } from "./ApplicationsTable";

// Même seuil que le compteur « offres pertinentes » de l'accueil (backend/app/dashboard.py).
const RELEVANT_SCORE = 3.5;
const PAGE_SIZE = 10;

const CONTRACTS: [ContractType | "", string][] = [
  ["", "Tous"],
  ["internship", "Stage"],
  ["apprenticeship", "Alternance"],
  ["fixed_term", "CDD"],
  ["permanent", "CDI"],
  ["other", "Autre"],
];
const CONTRACT_LABEL = Object.fromEntries(CONTRACTS.filter(([key]) => key)) as Record<ContractType, string>;

/** L'adresse vient d'une source externe : seuls http et https deviennent un lien. */
const safeUrl = (url: string) => (/^https?:\/\//i.test(url) ? url : undefined);

type Props = {
  /** Offres pour lesquelles une candidature existe déjà. */
  preparedIds: ReadonlySet<string>;
  /** Crée une candidature « à préparer » ; renvoie `null` si réussi, sinon le message d'erreur. */
  onPrepare: (offer: Offer) => Promise<string | null>;
};

type OfferPage = { items: Offer[]; total: number };

async function fetchOffers(api: Api, page: number, kind: ContractType | ""): Promise<OfferPage> {
  const query = {
    page,
    page_size: PAGE_SIZE,
    min_score: RELEVANT_SCORE,
    sort: "score_desc" as const,
    ...(kind ? { contract_type: [kind] } : {}),
  };
  return unwrap(await api.GET("/offers", { params: { query } }));
}

export function OffersPage({ preparedIds, onPrepare }: Props) {
  const api = useApi();
  const [contract, setContract] = useState<ContractType | "">("");
  const [offers, setOffers] = useState<Offer[]>([]);
  const [total, setTotal] = useState(0);
  const [phase, setPhase] = useState<"loading" | "ready" | "error">("loading");
  const [problem, setProblem] = useState<string | null>(null);
  const current = useRef<ContractType | "">("");

  const show = useCallback((page: number, kind: ContractType | "", result: OfferPage) => {
    if (kind !== current.current) return; // un autre filtre a été choisi entre-temps
    setOffers((before) => (page === 1 ? result.items : [...before, ...result.items]));
    setTotal(result.total);
    setPhase("ready");
  }, []);

  useEffect(() => {
    let active = true;
    fetchOffers(api, 1, contract)
      .then((result) => active && show(1, contract, result))
      .catch(() => active && setPhase("error"));
    return () => {
      active = false;
    };
  }, [api, contract, show]);

  function choose(kind: ContractType | "") {
    current.current = kind;
    setPhase("loading");
    setContract(kind);
  }

  function more(page: number, kind: ContractType | "") {
    fetchOffers(api, page, kind)
      .then((result) => show(page, kind, result))
      .catch(() => setProblem("Chargement des offres suivantes impossible."));
  }

  async function prepare(offer: Offer) {
    setProblem(await onPrepare(offer));
  }

  return (
    <>
      <h1>
        {total} {total > 1 ? "offres pertinentes" : "offre pertinente"}
      </h1>
      <p className="muted">Triées par score. Le score compare l'offre à vos critères et à votre profil.</p>
      <div className="segmented" role="group" aria-label="Type de contrat">
        {CONTRACTS.map(([key, label]) => (
          <button key={key} type="button" aria-pressed={contract === key} onClick={() => choose(key)}>
            {label}
          </button>
        ))}
      </div>

      {problem && (
        <p role="alert" className="error">
          {problem}
        </p>
      )}
      {phase === "loading" && <p role="status">Chargement…</p>}
      {phase === "error" && (
        <p role="alert" className="error">
          Chargement des offres impossible.{" "}
          <button type="button" onClick={() => choose(contract)}>
            Réessayer
          </button>
        </p>
      )}
      {phase === "ready" && offers.length === 0 && (
        <p className="muted">
          {contract
            ? "Aucune offre pertinente pour ce type de contrat."
            : "Aucune offre pertinente pour l'instant. Elles apparaîtront après la prochaine collecte."}
        </p>
      )}
      {phase === "ready" && offers.length > 0 && (
        <ul className="offer-list" aria-label="Offres pertinentes">
          {offers.map((offer) => {
            const url = safeUrl(offer.url);
            return (
              <li key={offer.id} className="offer">
                <div className="offer-score">
                  <Score value={offer.score} />
                </div>
                <div>
                  <h3>
                    {offer.title}
                    {offer.contract_type && <span className="chip">{CONTRACT_LABEL[offer.contract_type]}</span>}
                  </h3>
                  <p>{[offer.company, offer.location].filter(Boolean).join(" · ")}</p>
                  {offer.explanation && <p>{offer.explanation}</p>}
                  {url && (
                    <a className="offer-link" href={url} target="_blank" rel="noopener noreferrer">
                      Voir l'annonce d'origine
                    </a>
                  )}
                </div>
                <div className="offer-action">
                  {preparedIds.has(offer.id) ? (
                    <span className="chip">Dans vos candidatures</span>
                  ) : (
                    <button type="button" className="primary" onClick={() => void prepare(offer)}>
                      Préparer la candidature
                    </button>
                  )}
                </div>
              </li>
            );
          })}
        </ul>
      )}
      {phase === "ready" && offers.length < total && (
        <button type="button" onClick={() => more(Math.floor(offers.length / PAGE_SIZE) + 1, contract)}>
          Voir plus d'offres
        </button>
      )}
    </>
  );
}
