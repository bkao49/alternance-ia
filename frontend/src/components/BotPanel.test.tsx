import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { BotStatus } from "../api/types";
import { BotPanel } from "./BotPanel";

const status: BotStatus = {
  next_run_at: new Date(Date.now() + 134 * 60_000).toISOString(),
  sources: [{ source: "adzuna", state: "error", cause: "source indisponible" }, { source: "lba", state: "disabled", cause: "Source non activée" }],
  activity: [{ at: "2026-10-30T14:02:00Z", source: "adzuna", outcome: "done", message: "61 offres lues, 4 nouvelles" }],
};

describe("bloc du bot", () => {
  it("affiche le journal, les sources en échec et la prochaine collecte", () => {
    render(<BotPanel status={status} />);
    const bot = screen.getByRole("region", { name: "Le bot travaille" });
    expect(within(bot).getByRole("list", { name: "Dernières actions du bot" })).toHaveTextContent("adzuna : 61 offres lues, 4 nouvelles");
    expect(within(bot).getByRole("list", { name: "Sources à surveiller" })).toHaveTextContent("adzuna : en échec, source indisponible");
    expect(bot).not.toHaveTextContent("lba");
    expect(bot).toHaveTextContent(/prochaine collecte, dans 2 h 1\d min/);
  });

  it("dit honnêtement qu'il n'y a rien quand le statut est absent ou vide", () => {
    const { rerender } = render(<BotPanel />);
    expect(screen.getByRole("region", { name: "Le bot" })).toHaveTextContent("Aucune collecte pour l'instant");
    rerender(<BotPanel status={{ sources: [], activity: [] }} />);
    expect(screen.queryByRole("list")).not.toBeInTheDocument();
  });
});
