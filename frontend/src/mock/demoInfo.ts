// Identifiants du mode démonstration. Importé uniquement par le code de démonstration et par App
// derrière `import.meta.env.MODE === "mock"` : le build de production ne les contient pas.
export const DEMO = { email: "demo@example.test", password: "demo-demo" } as const;

// Journal fictif du bot pour la démonstration : aucune route de collecte n'existe encore côté API.
export const BOT_DEMO = {
  minutesToNext: 134,
  steps: [
    ["14:02", "Source A : 61 offres lues"],
    ["14:03", "Source B : 38 offres lues"],
    ["14:03", "Analyse de Data Engineer, Initech Data"],
    ["14:03", "Score 4,4 sur 5, confiance élevée"],
    ["14:04", "Analyse de ML Engineer, Globex IA"],
    ["14:04", "Score 4,6 sur 5, nouvelle offre pertinente"],
  ],
} as const;
