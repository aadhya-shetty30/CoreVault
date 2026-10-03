import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useAuth } from "../context/AuthContext.jsx";
import { useToast } from "../context/ToastContext.jsx";
import { ApiError } from "../api/client";
import AuthLayout from "../components/AuthLayout.jsx";

export default function LoginPage() {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [code, setCode] = useState("");
  const [pendingToken, setPendingToken] = useState(null); // set once password step succeeds on a 2FA account
  const [submitting, setSubmitting] = useState(false);
  const { login, verifyTwoFactor } = useAuth();
  const { notify } = useToast();
  const navigate = useNavigate();

  async function handlePasswordSubmit(e) {
    e.preventDefault();
    setSubmitting(true);
    try {
      const result = await login(email, password);
      if (result.requiresTwoFactor) {
        setPendingToken(result.pendingToken);
      } else {
        navigate("/app");
      }
    } catch (err) {
      notify(err instanceof ApiError ? String(err.detail) : "Login failed");
    } finally {
      setSubmitting(false);
    }
  }

  async function handleCodeSubmit(e) {
    e.preventDefault();
    setSubmitting(true);
    try {
      await verifyTwoFactor(pendingToken, code);
      navigate("/app");
    } catch (err) {
      notify(err instanceof ApiError ? String(err.detail) : "Invalid code");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <AuthLayout
      title={pendingToken ? "Two-factor code" : "Welcome back"}
      subtitle={pendingToken ? "Enter the 6-digit code from your authenticator app." : "Sign in to your account"}
    >
      {pendingToken ? (
        <form onSubmit={handleCodeSubmit} className="space-y-4">
          <input
            type="text"
            inputMode="numeric"
            autoFocus
            required
            minLength={6}
            maxLength={6}
            value={code}
            onChange={(e) => setCode(e.target.value.replace(/\D/g, ""))}
            className="w-full rounded-lg bg-white px-3 py-3 text-center text-xl tracking-[0.5em] ring-1 ring-slate-200 focus:outline-none focus:ring-2 focus:ring-indigo-500"
            placeholder="000000"
          />
          <button
            type="submit"
            disabled={submitting || code.length !== 6}
            className="w-full rounded-lg bg-indigo-600 py-2.5 text-sm text-white font-medium shadow-sm hover:bg-indigo-700 disabled:opacity-50"
          >
            {submitting ? "Verifying..." : "Verify"}
          </button>
          <button
            type="button"
            onClick={() => {
              setPendingToken(null);
              setCode("");
            }}
            className="w-full text-sm text-slate-500 hover:underline"
          >
            Back to password
          </button>
        </form>
      ) : (
        <form onSubmit={handlePasswordSubmit} className="space-y-4">
          <div>
            <label className="block text-sm font-medium text-slate-700">Email</label>
            <input
              type="email"
              required
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              className="mt-1.5 w-full rounded-lg bg-white px-3.5 py-2.5 text-sm text-slate-900 ring-1 ring-slate-200 placeholder:text-slate-400 focus:outline-none focus:ring-2 focus:ring-indigo-500"
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-slate-700">Password</label>
            <input
              type="password"
              required
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="mt-1.5 w-full rounded-lg bg-white px-3.5 py-2.5 text-sm text-slate-900 ring-1 ring-slate-200 placeholder:text-slate-400 focus:outline-none focus:ring-2 focus:ring-indigo-500"
            />
          </div>
          <button
            type="submit"
            disabled={submitting}
            className="w-full rounded-lg bg-indigo-600 py-2.5 text-sm text-white font-medium shadow-sm hover:bg-indigo-700 disabled:opacity-50"
          >
            {submitting ? "Signing in..." : "Sign in"}
          </button>
          <p className="text-sm text-center text-slate-500">
            No account?{" "}
            <Link to="/register" className="font-medium text-indigo-600 hover:text-indigo-700">
              Create one
            </Link>
          </p>
        </form>
      )}
    </AuthLayout>
  );
}
