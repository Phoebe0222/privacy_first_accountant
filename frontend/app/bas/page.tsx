"use client";
import { useEffect, useState } from "react";
import { api, BasResult } from "@/lib/api";

function fyStartYear(): number {
  const now = new Date();
  return now.getMonth() >= 6 ? now.getFullYear() : now.getFullYear() - 1;
}

function currentQuarter(): string {
  const m = new Date().getMonth(); // 0-indexed
  if (m >= 6 && m <= 8) return "Q1";
  if (m >= 9 && m <= 11) return "Q2";
  if (m >= 0 && m <= 2) return "Q3";
  return "Q4";
}

function fmt(n: number) {
  return new Intl.NumberFormat("en-AU", { style: "currency", currency: "AUD" }).format(n);
}

const QUARTER_LABELS: Record<string, string> = {
  Q1: "Q1 Jul – Sep",
  Q2: "Q2 Oct – Dec",
  Q3: "Q3 Jan – Mar",
  Q4: "Q4 Apr – Jun",
  annual: "Full Year",
};

export default function BASPage() {
  const [year, setYear] = useState(fyStartYear());
  const [quarter, setQuarter] = useState(currentQuarter());
  const [result, setResult] = useState<BasResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string>("");
  const [taxProfile, setTaxProfile] = useState<{ income_type: string; gst_registered: boolean } | null>(null);

  useEffect(() => {
    api.getTaxProfile().then(setTaxProfile).catch(() => {});
  }, []);

  function load() {
    setLoading(true);
    setError("");
    api.getBas(year, quarter)
      .then(setResult)
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }

  useEffect(() => { load(); }, [year, quarter]);

  const fyOptions = Array.from({ length: 5 }, (_, i) => fyStartYear() - i);

  return (
    <div className="space-y-6 max-w-3xl">
      <div>
        <h2 className="text-2xl font-bold text-gray-800">BAS / GST</h2>
        <p className="text-sm text-gray-400 mt-1">Business Activity Statement estimate based on bank transactions marked as business.</p>
      </div>

      {/* Not applicable notices */}
      {taxProfile?.income_type === "employment" && (
        <div className="bg-gray-50 border border-gray-200 rounded-xl p-5 space-y-1">
          <p className="font-medium text-gray-700">BAS not required</p>
          <p className="text-sm text-gray-500">Your tax profile is set to Employment only. BAS / GST reporting applies to businesses, not PAYG salary earners.</p>
          <a href="/tax-settings" className="text-sm text-blue-500 hover:underline">Change in Tax Settings →</a>
        </div>
      )}

      {taxProfile && taxProfile.income_type !== "employment" && !taxProfile.gst_registered && (
        <div className="bg-amber-50 border border-amber-200 rounded-xl p-5 space-y-1">
          <p className="font-medium text-amber-800">Not registered for GST</p>
          <p className="text-sm text-amber-700">
            BAS is only required once you are registered for GST (mandatory when annual turnover ≥ $75,000,
            or voluntary below that). Your estimate is shown below for reference, but no BAS needs to be lodged.
          </p>
          <a href="/tax-settings" className="text-sm text-blue-500 hover:underline">Update GST status in Tax Settings →</a>
        </div>
      )}

      {/* Period selectors */}
      <div className="flex gap-3 items-center">
        <select value={year} onChange={(e) => setYear(Number(e.target.value))}
          className="border border-gray-200 rounded-lg px-3 py-2 text-sm bg-white">
          {fyOptions.map((y) => (
            <option key={y} value={y}>FY {y}–{String(y + 1).slice(2)}</option>
          ))}
        </select>
        <div className="flex gap-1">
          {Object.entries(QUARTER_LABELS).map(([q, label]) => (
            <button key={q} onClick={() => setQuarter(q)}
              className={`px-3 py-2 rounded-lg text-sm transition-colors ${
                quarter === q ? "bg-blue-600 text-white" : "bg-white border border-gray-200 text-gray-600 hover:bg-gray-50"
              }`}>
              {label}
            </button>
          ))}
        </div>
      </div>

      {error && <p className="text-red-500 text-sm">{error}</p>}

      {loading ? (
        <p className="text-gray-400">Calculating…</p>
      ) : result && (
        <>
          {/* GST threshold warning */}
          {result.gst_registration_warning && (
            <div className="bg-amber-50 border border-amber-200 rounded-xl px-4 py-3 text-sm text-amber-700">
              ⚠️ Annualised income ({fmt(result.annualised_income)}) is approaching or exceeding the $75,000 GST registration threshold.
            </div>
          )}

          <p className="text-xs text-gray-400">{result.period} · {result.date_range} · {result.transaction_count} transactions</p>

          {/* BAS summary cards */}
          <div className="grid grid-cols-2 gap-4">
            <div className="bg-white rounded-xl border border-gray-100 shadow-sm p-5">
              <p className="text-xs text-gray-400 mb-1">G1 — Total Sales</p>
              <p className="text-2xl font-bold text-gray-800">{fmt(result.G1)}</p>
            </div>
            <div className="bg-white rounded-xl border border-gray-100 shadow-sm p-5">
              <p className="text-xs text-gray-400 mb-1">G11 — Total Purchases</p>
              <p className="text-2xl font-bold text-gray-800">{fmt(result.G11)}</p>
            </div>
            <div className="bg-white rounded-xl border border-gray-100 shadow-sm p-5">
              <p className="text-xs text-gray-400 mb-1">1A — GST on Sales (collected)</p>
              <p className="text-2xl font-bold text-green-700">{fmt(result.tax_1A)}</p>
              {result.tax_1A === 0 && result.G1 > 0 && (
                <p className="text-xs text-gray-400 mt-1">No GST recorded on sales — check if tax fields are populated.</p>
              )}
            </div>
            <div className="bg-white rounded-xl border border-gray-100 shadow-sm p-5">
              <p className="text-xs text-gray-400 mb-1">1B — GST Credits (input tax)</p>
              <p className="text-2xl font-bold text-blue-700">{fmt(result.tax_1B)}</p>
              {result.tax_1B === 0 && result.G11 > 0 && (
                <p className="text-xs text-gray-400 mt-1">No GST credits recorded — check if tax fields are populated.</p>
              )}
            </div>
          </div>

          {/* Net GST */}
          <div className={`rounded-xl border shadow-sm p-5 ${
            result.net_gst > 0 ? "bg-red-50 border-red-200" : result.net_gst < 0 ? "bg-green-50 border-green-200" : "bg-white border-gray-100"
          }`}>
            <p className="text-xs text-gray-500 mb-1">Net GST (1A − 1B)</p>
            <p className={`text-3xl font-bold ${result.net_gst > 0 ? "text-red-600" : result.net_gst < 0 ? "text-green-600" : "text-gray-500"}`}>
              {fmt(result.net_gst)}
            </p>
            <p className="text-sm mt-1 text-gray-500">
              {result.net_gst > 0
                ? "Payable to ATO"
                : result.net_gst < 0
                ? "Refund from ATO"
                : "No net GST"}
            </p>
          </div>

          <p className="text-xs text-gray-400">
            Estimates only — only bank transactions marked as Business are included.
            Consult a registered tax agent or BAS agent before lodging.
          </p>
        </>
      )}
    </div>
  );
}
