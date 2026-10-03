import { useEffect, useState } from "react";
import { QRCodeSVG } from "qrcode.react";
import { apiRequest, ApiError } from "../api/client";
import { useAuth } from "../context/AuthContext.jsx";
import { useToast } from "../context/ToastContext.jsx";
import useEscapeKey from "../lib/useEscapeKey";

/** Two-step 2FA enrollment: fetch a secret + otpauth URI, render it as a QR
 * code (scan with any authenticator app), then confirm with one code before
 * the backend actually flips otp_enabled -- see POST /auth/2fa/setup and
 * /auth/2fa/verify-setup in app/routers/auth.py. */
export default function TwoFactorSetupModal({ onClose }) {
  useEscapeKey(onClose);
  const { token, refreshUser } = useAuth();
  const { notify } = useToast();
  const [setupData, setSetupData] = useState(null); // { secret, otpauth_uri }
  const [code, setCode] = useState("");
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    apiRequest("/auth/2fa/setup", { method: "POST", token })
      .then(setSetupData)
      .catch((err) => notify(err instanceof ApiError ? String(err.detail) : "Could not start 2FA setup"))
      .finally(() => setLoading(false));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function handleVerify(e) {
    e.preventDefault();
    setSubmitting(true);
    try {
      await apiRequest("/auth/2fa/verify-setup", { method: "POST", token, json: { code } });
      await refreshUser();
      notify("Two-factor authentication enabled", "success");
      onClose();
    } catch (err) {
      notify(err instanceof ApiError ? String(err.detail) : "Invalid code");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="fixed inset-0 bg-slate-900/20 backdrop-blur-[2px] flex items-center justify-center z-50 p-4">
      <div className="bg-white rounded-2xl shadow-xl ring-1 ring-slate-900/5 w-full max-w-sm p-6 space-y-4">
        <h2 className="text-lg font-semibold text-slate-800">Enable two-factor authentication</h2>
        {loading ? (
          <p className="text-sm text-slate-400">Loading...</p>
        ) : setupData ? (
          <>
            <p className="text-sm text-slate-500">Scan this QR code with an authenticator app (e.g. Google Authenticator, Authy).</p>
            <div className="flex justify-center bg-white p-3 rounded border">
              <QRCodeSVG value={setupData.otpauth_uri} size={180} />
            </div>
            <p className="text-xs text-slate-400 break-all">Or enter this secret manually: {setupData.secret}</p>
            <form onSubmit={handleVerify} className="space-y-3">
              <input
                type="text"
                inputMode="numeric"
                required
                minLength={6}
                maxLength={6}
                autoFocus
                value={code}
                onChange={(e) => setCode(e.target.value.replace(/\D/g, ""))}
                placeholder="Enter the 6-digit code"
                className="w-full rounded-lg border border-slate-200 px-3 py-2 text-center tracking-[0.4em] focus:outline-none focus:ring-2 focus:ring-indigo-500"
              />
              <div className="flex gap-2">
                <button
                  type="button"
                  onClick={onClose}
                  className="flex-1 rounded-lg border border-slate-200 py-2 text-sm text-slate-600 hover:bg-slate-50"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={submitting || code.length !== 6}
                  className="flex-1 rounded-lg bg-indigo-600 py-2 text-sm text-white hover:bg-indigo-700 disabled:opacity-50"
                >
                  {submitting ? "Verifying..." : "Confirm"}
                </button>
              </div>
            </form>
          </>
        ) : (
          <button onClick={onClose} className="text-sm text-slate-500 hover:underline">
            Close
          </button>
        )}
      </div>
    </div>
  );
}
