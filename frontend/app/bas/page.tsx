"use client";
import { useEffect, useState } from "react";
import { api, BasResult } from "@/lib/api";

function fmt(n: number) {
  return new Intl.NumberFormat("en-AU", { style: "currency", currency: "AUD" }).format(n);
}

function currentFY() {
  const now = new Date();
  // AUS FY ends June 30. If month < July (0-5), FY year = current year; else FY year = next year.
  return now.getMonth() < 6 ? now.getFullYear() : now.getFullYear() + 1;
}

function currentQuarter() {
  const m = new Date().getMonth(); // 0=Jan
  if (m >= 6 && m <= 8) return "Q1";
  if (m >= 9) return "Q2";
  if (m <= 2) return "Q3";
  return "Q4";
}

const FY_RANGE = Array.from({ length: 6 }, (_, i) => currentFY() - i);
const QUARTERS = ["Q1", "Q2", "Q3", "Q4", "annual"];

function BasCard({ label, value, sub, highlight }: { label: string; value: string; sub?: string; highlight?: "positive" | "negative" | "neutral" }) {
  const color = highlight === "positive" ? "text-green-600" : highlight === "negative" ? "text-red-600" : "text-blue-700";
  return (
    <div className="bg-white rounded-xl border border-gray-100 shadow-sm p-5">
      <p className="text-xs text-gray-500 uppercase tracking-wide mb-1">{label}</p>
      <p className={`text-2xl font-bold ${color}`}>{value}</p>
      {sub && <p className="text-xs text-gray-400 mt-1">{sub}</p>}
    </div>
  );
}

export default function BasPage() {
  const [fy, setFy] = useState(currentFY());
  const [quarter, setQuarter] = useState(currentQuarter());
  const [result, setResult] = useState<BasResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    setLoading(true);
    setError("");
    api.getBas(fy, quarter)
      .then(setResult)
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, [fy, quarter]);

  return (
    <div className="space-y-6 max-w-3xl">
      <h2 className="text-2xl font-bold text-gray-800">BAS / GST Estimate</h2>

      <div className="flex items-center gap-4">
        <div>
          <label className="text-xs text-gray-500 mb-1 block">Financial Year</label>
          <select
            value={fy}
            onChange={(e) => setFy(Number(e.target.value))}
            className="border border-gray-200 rounded-lg px-3 py-2 text-sm bg-white"
          >
            {FY_RANGE.map((y) => (
              <option key={y} value={y}>FY{y} (Jul {y - 1} – Jun {y})</option>
            ))}
          </select>
        </div>
        <div>
          <label className="text-xs text-gray-500 mb-1 block">Period</label>
          <div className="flex gap-1">
            {QUARTERS.map((q) => (
              <button
                key={q}
                onClick={() => setQuarter(q)}
                className={`px-3 py-2 rounded-lg text-sm border transition-colors ${
                  quarter === q
                    ? "bg-blue-600 text-white border-blue-600"
                    : "border-gray-200 text-gray-600 hover:bg-gray-50"
                }`}
              >
                {q === "annual" ? "Annual" : q}
              </button>
            ))}
          </div>
        </div>
      </div>

      {error && <p className="text-red-500 text-sm">{error}</p>}

      {loading ? (
        <p className="text-gray-400">Calculating…</p>
      ) : result ? (
        <>
          <div className="flex items-center gap-2 text-sm text-gray-400">
            <span>{result.date_range}</span>
            <span>·</span>
            <span>{result.transaction_count} bank/manual transactions</span>
          </div>

          {result.gst_registration_warning && (
            <div className="bg-amber-50 border border-amber-200 rounded-xl px-4 py-3 text-sm text-amber-800">
              ⚠️ Your annualised turnover is approaching or exceeds the $75,000 GST registration threshold. You may need to register for GST.
            </div>
          )}

          <div className="grid grid-cols-2 gap-4">
            <BasCard
              label="G1 — Total Sales"
              value={fmt(result.G1)}
              sub="Total income from bank CSV and manual entries"
              highlight="neutral"
            />
            <BasCard
              label="G11 — Total Acquisitions"
              value={fmt(result.G11)}
              sub="Total business expenses"
              highlight="neutral"
            />
            <BasCard
              label="1A — GST on Sales"
              value={fmt(result.tax_1A)}
              sub="GST collected from customers"
              highlight="neutral"
            />
            <BasCard
              label="1B — Input Tax Credits"
              value={fmt(result.tax_1B)}
              sub="GST you paid on business expenses"
              highlight="neutral"
            />
          </div>

          <div className={`rounded-xl border-2 p-6 flex items-center justify-between ${
            result.net_gst >= 0 ? "bg-red-50 border-red-200" : "bg-green-50 border-green-200"
          }`}>
            <div>
              <p className="text-sm font-medium text-gray-600">Net GST {result.net_gst >= 0 ? "Payable to ATO" : "Refundable from ATO"}</p>
              <p className="text-xs text-gray-400 mt-0.5">1A minus 1B</p>
            </div>
            <p className={`text-3xl font-bold ${result.net_gst >= 0 ? "text-red-600" : "text-green-600"}`}>
              {fmt(Math.abs(result.net_gst))}
            </p>
          </div>

          <p className="text-xs text-gray-400">
            Only bank CSV and manually entered transactions marked as &quot;Business&quot; are included. This is an estimate — consult a registered tax agent for final BAS lodgement.
          </p>
        </>
      ) : null}
    </div>
  );
}
