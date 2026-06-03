"use client";
import { useEffect, useState } from "react";
import { api, Transaction } from "@/lib/api";

function fmt(n: number) {
  return new Intl.NumberFormat("en-AU", { style: "currency", currency: "AUD" }).format(n);
}

export default function AnomaliesPage() {
  const [items, setItems] = useState<Transaction[]>([]);
  const [loading, setLoading] = useState(true);
  const [dismissing, setDismissing] = useState<number | null>(null);

  function load() {
    setLoading(true);
    api
      .getTransactions({ anomaly: true })
      .then(({ items }) => setItems(items))
      .finally(() => setLoading(false));
  }

  useEffect(() => { load(); }, []);

  async function handleDismiss(id: number) {
    setDismissing(id);
    try {
      await api.dismissAnomaly(id);
      load();
    } finally {
      setDismissing(null);
    }
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center gap-3">
        <h2 className="text-2xl font-bold text-gray-800">Anomalies</h2>
        {!loading && (
          <span className={`text-sm font-medium px-2.5 py-0.5 rounded-full ${
            items.length > 0 ? "bg-orange-100 text-orange-700" : "bg-green-100 text-green-700"
          }`}>
            {items.length > 0 ? `${items.length} flagged` : "All clear"}
          </span>
        )}
      </div>

      <p className="text-sm text-gray-400">
        Transactions flagged by AI as unusual compared to past records. Review and dismiss false positives.
      </p>

      {loading ? (
        <p className="text-gray-400">Loading…</p>
      ) : items.length === 0 ? (
        <div className="bg-white rounded-xl border border-gray-100 shadow-sm p-12 text-center">
          <p className="text-3xl mb-3">✅</p>
          <p className="text-gray-500 font-medium">No anomalies detected</p>
          <p className="text-sm text-gray-400 mt-1">Unusual transactions will appear here when found during import.</p>
        </div>
      ) : (
        <div className="bg-white rounded-xl shadow-sm border border-gray-100 overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-gray-50 text-gray-500 text-xs uppercase tracking-wide">
              <tr>
                <th className="px-4 py-3 text-left">Date</th>
                <th className="px-4 py-3 text-left">Vendor</th>
                <th className="px-4 py-3 text-left">Type</th>
                <th className="px-4 py-3 text-right">Amount</th>
                <th className="px-4 py-3 text-left">Reason</th>
                <th className="px-4 py-3"></th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-50">
              {items.map((t) => (
                <tr key={t.id} className="hover:bg-orange-50 transition-colors">
                  <td className="px-4 py-3 text-gray-600">{t.date}</td>
                  <td className="px-4 py-3 font-medium text-gray-800">{t.vendor}</td>
                  <td className="px-4 py-3">
                    <span className={`text-xs font-medium px-2 py-0.5 rounded ${
                      t.type === "income" ? "bg-green-100 text-green-700" : "bg-red-100 text-red-700"
                    }`}>
                      {t.type}
                    </span>
                  </td>
                  <td className={`px-4 py-3 text-right font-medium ${
                    t.type === "income" ? "text-green-600" : "text-gray-800"
                  }`}>
                    {fmt(t.amount)}
                  </td>
                  <td className="px-4 py-3 text-orange-600 text-xs max-w-xs">{t.anomaly_reason ?? "—"}</td>
                  <td className="px-4 py-3 text-right">
                    <button
                      onClick={() => handleDismiss(t.id)}
                      disabled={dismissing === t.id}
                      className="text-xs text-gray-400 hover:text-gray-700 disabled:opacity-50 transition-colors"
                    >
                      {dismissing === t.id ? "Dismissing…" : "Dismiss"}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
