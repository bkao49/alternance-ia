// Chiffres entièrement fictifs, pour illustrer la page. Les totaux affichés dans index.html en découlent
// (vérifié par data.test.ts).

// Offres lues chaque jour sur 30 jours.
export const COLLECTED = [
  31, 36, 28, 40, 44, 22, 18, 39, 47, 42, 51, 45, 20, 17, 43, 49, 55, 48, 52, 24, 21, 50, 57, 53, 61, 49, 26,
  23, 54, 59,
];

// Offres analysées par tranche de score : [1 ; 1,5[, [1,5 ; 2[, … [4,5 ; 5].
export const SCORE_BINS = [6, 14, 27, 41, 52, 44, 10, 4];
export const SCORE_FROM = 1;
export const SCORE_STEP = 0.5;

export const total = (values: number[]) => values.reduce((a, b) => a + b, 0);
