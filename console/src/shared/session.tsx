import { useQuery, useQueryClient } from "@tanstack/react-query";
import { createContext, type ReactNode, useCallback, useContext, useState } from "react";
import { api, hasToken, type Me, setToken } from "./api/client";

type Session = { me: Me | undefined; loading: boolean; error: unknown; signIn: (user: string) => Promise<void>; signOut: () => void; retry: () => void };
const Ctx = createContext<Session | null>(null);

export function SessionProvider({ children }: { children: ReactNode }) {
  const qc = useQueryClient();
  const [signedIn, setSignedIn] = useState(hasToken());
  const me = useQuery({ queryKey: ["me"], queryFn: api.me, enabled: signedIn, retry: false });
  const signIn = useCallback(
    async (user: string) => {
      const { token } = await api.login(user);
      setToken(token);
      qc.clear();
      setSignedIn(true);
      await qc.invalidateQueries();
    },
    [qc],
  );
  const signOut = useCallback(() => {
    setToken(null);
    qc.clear();
    setSignedIn(false);
  }, [qc]);
  return <Ctx.Provider value={{ me: signedIn ? me.data : undefined, loading: signedIn && me.isPending, error: me.error, signIn, signOut, retry: () => me.refetch() }}>{children}</Ctx.Provider>;
}

export function useSession(): Session {
  const s = useContext(Ctx);
  if (!s) throw new Error("useSession outside SessionProvider");
  return s;
}
