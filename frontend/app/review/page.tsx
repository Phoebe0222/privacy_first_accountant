"use client";
import { useEffect, useState } from "react";
import { api, Transaction } from "@/lib/api";

const CATEGORIES = ["food", "grocery", "cafe", "transport", "travel", "utilities", "software", "marketing", "revenue", "salary", "refund", "office", "subscription", "shopping", "leisure", "material", "fee", "gym", "medical", "other"];

function fmt(n: number) {
  return new Intl.NumberFormat("en-AU", { style: "currency", currency: "AUD" }).format(n);
}

function ConfidenceBadge({ value }: { value?: number }) {
  if (value === undefined) return null;
  const pct = Math.round(value * 100);
  const color = pct >= 70 ? "bg-green-100 text-green-700" : pct >= 40 ? "bg-yellow-100 text-yellow-700" : "bg-red-100 text-red-700";
  return <span className={`text-xs font-medium px-2 py-0.5 rounded ${color}`}>{pct}%</span>;
}

function ReviewRow({ t, onFixed }: { t: Transaction; onFixed: () => void }) {
  const [category, setCategory] = useState(t.category);
  const [saving, setSaving] = useState(false);

  async function save() {
    if (category === t.category) return;
    setSaving(true);
    await api.updateTransaction(t.id, { category });
    setSaving(false);
    onFixed();
  }

  return (
    <tr className="hover:bg-gray-50">
      <td className="px-4 py-3 text-gray-600 text-sm">{t.date}</td>
      <td className="px-4 py-3 font-medium text-gray-800 text-sm">{t.vendor}</td>
      <td className={`px-4 py-3 text-sm font-medium text-right ${t.type === "income" ? "text-green-600" : "text-gray-800"}`}>
        {fmt(t.amount)}
      </td>
      <td className="px-4 py-3">
        <div className="flex items-center gap-2">
          <select
            value={category}
            onChange={(e) => setCategory(e.target.value)}
            className="border border-gray-200 rounded px-2 py-1 text-sm"
          >
            {CATEGORIES.map((c) => <option key={c} value={c}>{c}</option>)}
          </select>
          <ConfidenceBadge value={t.category_confidence} />
        </div>
      </td>
      <td className="px-4 py-3 text-sm text-gray-400 max-w-xs truncate">{t.description}</td>
      <td className="px-4 py-3 text-right">
        <button
          onClick={save}
          disabled={saving || category === t.category}
          className="text-xs bg-blue-600 text-white px-3 py-1 rounded hover:bg-blue-700 disabled:opacity-40"
        >
          {saving ? "Saving…" : "Confirm"}
        </button>
      </td>
    </tr>
  );
}

function AnomalyRow({ t }: { t: Transaction }) {
  return (
    <tr className="hover:bg-gray-50">
      <td className="px-4 py-3 text-gray-600 text-sm">{t.date}</td>
      <td className="px-4 py-3 font-medium text-gray-800 text-sm">{t.vendor}</td>
      <td className={`px-4 py-3 text-sm font-medium text-right ${t.type === "income" ? "text-green-600" : "text-gray-800"}`}>
        {fmt(t.amount)}
      </td>
      <td className="px-4 py-3 text-sm capitalize text-gray-500">{t.category}</td>
      <td className="px-4 py-3 text-sm text-amber-600">{t.anomaly_reason}</td>
    </tr>
  );
}

export default function ReviewPage() {
  const [tab, setTab] = useState<"review" | "anomalies">("review");
  const [reviewItems, setReviewItems] = useState<Transaction[]>([]);
  const [anomalyItems, setAnomalyItems] = useState<Transaction[]>([]);
  const [loading, setLoading] = useState(true);

  function load() {
    setLoading(true);
    Promise.all([api.getReviewQueue(), api.getAnomalies()])
      .then(([rq, an]) => {
        setReviewItems(rq.items);
        setAnomalyItems(an.items);
      })
      .finally(() => setLoading(false));
  }

  useEffect(() => { load(); }, []);

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h2 className="text-2xl font-bold text-gray-800">Review</h2>
        <div className="flex gap-2">
          <button
            onClick={() => setTab("review")}
            className={`px-4 py-2 rounded-lg text-sm font-medium transition-colors ${tab === "review" ? "bg-blue-600 text-white" : "bg-white border border-gray-200 text-gray-600 hover:bg-gray-50"}`}
          >
            Category Review
            {reviewItems.length > 0 && (
              <span className="ml-2 bg-red-500 text-white text-xs rounded-full px-1.5 py-0.5">{reviewItems.length}</span>
            )}
          </button>
          <button
            onClick={() => setTab("anomalies")}
            className={`px-4 py-2 rounded-lg text-sm font-medium transition-colors ${tab === "anomalies" ? "bg-blue-600 text-white" : "bg-white border border-gray-200 text-gray-600 hover:bg-gray-50"}`}
          >
            Anomalies
            {anomalyItems.length > 0 && (
              <span className="ml-2 bg-amber-500 text-white text-xs rounded-full px-1.5 py-0.5">{anomalyItems.length}</span>
            )}
          </button>
        </div>
      </div>

      {loading ? (
        <p className="text-gray-400">Loading…</p>
      ) : tab === "review" ? (
        reviewItems.length === 0 ? (
          <div className="bg-white rounded-xl border border-gray-100 shadow-sm p-12 text-center">
            <p className="text-green-600 font-medium">All categories confirmed</p>
            <p className="text-gray-400 text-sm mt-1">No transactions need review.</p>
          </div>
        ) : (
          <div className="bg-white rounded-xl shadow-sm border border-gray-100 overflow-x-auto">
            <div className="px-4 py-3 border-b border-gray-50">
              <p className="text-sm text-gray-500">
                {reviewItems.length} transaction{reviewItems.length !== 1 ? "s" : ""} with low-confidence categories — lowest confidence first.
                Selecting the correct category and clicking Confirm clears the flag.
              </p>
            </div>
            <table className="w-full text-sm">
              <thead className="bg-gray-50 text-xs uppercase tracking-wide text-gray-500">
                <tr>
                  <th className="px-4 py-3 text-left">Date</th>
                  <th className="px-4 py-3 text-left">Vendor</th>
                  <th className="px-4 py-3 text-right">Amount</th>
                  <th className="px-4 py-3 text-left">Category</th>
                  <th className="px-4 py-3 text-left">Description</th>
                  <th className="px-4 py-3"></th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-50">
                {reviewItems.map((t) => <ReviewRow key={t.id} t={t} onFixed={load} />)}
              </tbody>
            </table>
          </div>
        )
      ) : (
        anomalyItems.length === 0 ? (
          <div className="bg-white rounded-xl border border-gray-100 shadow-sm p-12 text-center">
            <p className="text-green-600 font-medium">No anomalies detected</p>
            <p className="text-gray-400 text-sm mt-1">All transaction amounts look normal.</p>
          </div>
        ) : (
          <div className="bg-white rounded-xl shadow-sm border border-gray-100 overflow-x-auto">
            <div className="px-4 py-3 border-b border-gray-50">
              <p className="text-sm text-gray-500">
                {anomalyItems.length} transaction{anomalyItems.length !== 1 ? "s" : ""} with amounts that differ significantly from past transactions for the same vendor.
              </p>
            </div>
            <table className="w-full text-sm">
              <thead className="bg-gray-50 text-xs uppercase tracking-wide text-gray-500">
                <tr>
                  <th className="px-4 py-3 text-left">Date</th>
                  <th className="px-4 py-3 text-left">Vendor</th>
                  <th className="px-4 py-3 text-right">Amount</th>
                  <th className="px-4 py-3 text-left">Category</th>
                  <th className="px-4 py-3 text-left">Reason</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-50">
                {anomalyItems.map((t) => <AnomalyRow key={t.id} t={t} />)}
              </tbody>
            </table>
          </div>
        )
      )}
    </div>
  );
}
