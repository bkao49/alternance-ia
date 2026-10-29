import { createContext, useContext } from "react";

import { api as defaultApi, type Api } from "./client";

// Permet aux tests (et à la démo) de fournir un autre client sans toucher aux composants.
export const ApiContext = createContext<Api>(defaultApi);

export const useApi = () => useContext(ApiContext);
