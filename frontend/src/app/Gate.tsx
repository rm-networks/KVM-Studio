import { useEffect, useState } from "react";

import { api } from "../api/client";
import { GuestLogin } from "../features/sharing/GuestLogin";
import { App } from "./App";

/** On the LAN listener of sharing, a browser without a session logs in first. */
export function Gate() {
  const [login, setLogin] = useState<boolean | null>(null);

  const check = () =>
    api
      .me()
      .then((me) => setLogin(me.sharing && me.role === null))
      .catch(() => setLogin(false));

  useEffect(() => {
    void check();
  }, []);

  if (login === null) return null;
  return login ? <GuestLogin onLoggedIn={() => void check()} /> : <App />;
}
