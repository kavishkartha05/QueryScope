import axios from "axios";
import { clearSession, getToken, notifyUnauthorized } from "./session";

const client = axios.create({
  baseURL: import.meta.env.VITE_API_URL || "http://localhost:8000",
  headers: { "Content-Type": "application/json" },
});

client.interceptors.request.use((config) => {
  const token = getToken();
  if (token) config.headers.Authorization = `Bearer ${token}`;
  return config;
});

client.interceptors.response.use(
  (response) => response,
  (error: unknown) => {
    // A 401 from login just means a bad code; the login flow reports it.
    // Any other 401 means the session is gone: drop the token and go back to
    // the landing page.
    if (axios.isAxiosError(error) && error.response?.status === 401) {
      const url = error.config?.url ?? "";
      if (!url.startsWith("/auth/login")) {
        clearSession();
        notifyUnauthorized();
      }
    }
    return Promise.reject(error);
  },
);

export default client;
