import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { BOT_DEMO } from "../mock/demoInfo";
import { BotPanel } from "./BotPanel";

describe("bloc du bot en démonstration", () => {
  it("affiche le journal et la prochaine collecte", () => {
    render(<BotPanel activity={BOT_DEMO} />);
    const bot = screen.getByRole("region", { name: "Le bot travaille" });
    expect(within(bot).getByText("En cours")).toBeInTheDocument();
    expect(within(bot).getByRole("list", { name: "Dernières actions du bot" })).toBeInTheDocument();
    expect(bot).toHaveTextContent(/prochaine collecte, dans 2 h 14 min/);
  });
});
