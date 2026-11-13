"use client";

import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";
import { api, getSavedPatient, getToken, savePatient, setToken, UNAUTHORIZED_EVENT, type Patient, type User } from "./api";

type Session = {
  user: User;
  patients: Patient[];
  patient: Patient | null;
  choosePatient: (id: number) => void;
  refreshPatients: (selectId?: number) => Promise<void>;
  logout: () => void;
};

const Ctx = createContext<Session | null>(null);

export function useSession(): Session {
  const s = useContext(Ctx);
  if (!s) throw new Error("useSession phải nằm trong SessionProvider");
  return s;
}

/** Hồ sơ đang chọn; các trang chỉ hiện khi đã có (layout lo phần tạo hồ sơ đầu tiên). */
export function usePatient(): Patient {
  const p = useSession().patient;
  if (!p) throw new Error("chưa chọn hồ sơ");
  return p;
}

type Status = "loading" | "anonymous" | "ready" | "error";

export function SessionProvider({ children, fallback }: { children: (s: Session) => ReactNode; fallback: (status: Status, error: string) => ReactNode }) {
  const [status, setStatus] = useState<Status>("loading");
  const [error, setError] = useState("");
  const [user, setUser] = useState<User | null>(null);
  const [patients, setPatients] = useState<Patient[]>([]);
  const [patientId, setPatientId] = useState<number | null>(null);

  const refreshPatients = useCallback(async (selectId?: number) => {
    const list = await api.patients();
    setPatients(list);
    const want = selectId ?? getSavedPatient();
    const chosen = list.find((p) => p.id === want) ?? list[0] ?? null;
    setPatientId(chosen?.id ?? null);
    savePatient(chosen?.id ?? null);
  }, []);

  useEffect(() => {
    const onUnauthorized = () => setStatus("anonymous");
    window.addEventListener(UNAUTHORIZED_EVENT, onUnauthorized);
    if (!getToken()) {
      setStatus("anonymous");
    } else {
      Promise.all([api.me(), refreshPatients()])
        .then(([me]) => {
          setUser(me);
          setStatus("ready");
        })
        .catch((e) => {
          setError(e.message);
          setStatus(getToken() ? "error" : "anonymous");
        });
    }
    return () => window.removeEventListener(UNAUTHORIZED_EVENT, onUnauthorized);
  }, [refreshPatients]);

  if (status !== "ready" || !user) return <>{fallback(status, error)}</>;
  const session: Session = {
    user,
    patients,
    patient: patients.find((p) => p.id === patientId) ?? null,
    choosePatient: (id) => {
      setPatientId(id);
      savePatient(id);
    },
    refreshPatients,
    logout: () => {
      setToken(null);
      savePatient(null);
      setStatus("anonymous");
    },
  };
  return <Ctx.Provider value={session}>{children(session)}</Ctx.Provider>;
}
