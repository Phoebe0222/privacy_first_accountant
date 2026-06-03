"use client";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";

const CATEGORIES = [
  "food", "grocery", "cafe", "transport", "travel", "utilities", "software",
  "marketing", "revenue", "salary", "refund", "office", "subscription",
  "shopping", "leisure", "material", "fee", "gym", "medical", "home_office", "other",
];

type VendorRule = { id: number; vendor_pattern: string; category: string };
type BuiltInRule = { vendor_pattern: string; category: string };

export default function VendorRulesTab() {
  const [rules, setRules] = useState<VendorRule[]>([]);
  const [builtIn, setBuiltIn] = useState<BuiltInRule[]>([]);
  const [pattern, setPattern] = useState("");
  const [category, setCategory] = useState("other");
  const [error, setError] = useState("");
  const [showBuiltIn, setShowBuiltIn] = useState(false);

  function load() { api.getVendorRules().then(setRules).catch(() => {}); }

  useEffect(() => {
    load();
    api.getBuiltInRules().then(setBuiltIn).catch(() => {});
  }, []);

  async function handleAdd(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    try {
      await api.createVendorRule(pattern.trim(), category);
      setPattern("");
      load();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to save rule");
    }
  }

  return (
    <div className="space-y-8">
      <p className="text-sm text-gray-500">
        Map vendor name patterns to categories. Custom rules take priority over built-ins.
        Matching is case-insensitive substring — e.g.{" "}
        <code className="bg-gray-100 px-1 rounded">aws</code> matches <em>Amazon AWS Invoice</em>.
      </p>

      <form onSubmit={handleAdd} className="bg-white border border-gray-100 rounded-xl p-6 shadow-sm space-y-4">
        <h3 className="font-semibold text-gray-700">Add Rule</h3>
        <div className="flex gap-3">
          <input
            required
            value={pattern}
            onChange={(e) => setPattern(e.target.value)}
            placeholder="Vendor pattern, e.g. woolworths"
            className="flex-1 border border-gray-200 rounded-lg px-3 py-2 text-sm"
          />
          <select
            value={category}
            onChange={(e) => setCategory(e.target.value)}
            className="border border-gray-200 rounded-lg px-3 py-2 text-sm bg-white"
          >
            {CATEGORIES.map((c) => <option key={c} value={c}>{c}</option>)}
          </select>
          <button type="submit" className="bg-blue-600 text-white px-4 py-2 rounded-lg text-sm hover:bg-blue-700">
            Add
          </button>
        </div>
        {error && <p className="text-red-500 text-sm">{error}</p>}
      </form>

      <section className="space-y-3">
        <h3 className="font-semibold text-gray-700">
          Custom Rules <span className="text-gray-400 font-normal">({rules.length})</span>
        </h3>
        {rules.length === 0 ? (
          <p className="text-sm text-gray-400">No custom rules yet.</p>
        ) : (
          <div className="bg-white border border-gray-100 rounded-xl shadow-sm overflow-hidden">
            <table className="w-full text-sm">
              <tbody className="divide-y divide-gray-50">
                {rules.map((r) => (
                  <tr key={r.id} className="hover:bg-gray-50">
                    <td className="px-4 py-3 font-mono text-gray-700">{r.vendor_pattern}</td>
                    <td className="px-4 py-3 capitalize text-gray-500">{r.category}</td>
                    <td className="px-4 py-3 text-right">
                      <button
                        onClick={() => api.deleteVendorRule(r.id).then(load)}
                        className="text-gray-300 hover:text-red-500 text-xs transition-colors"
                      >Delete</button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <section className="space-y-3">
        <button
          onClick={() => setShowBuiltIn((v) => !v)}
          className="flex items-center gap-2 text-sm font-semibold text-gray-500 hover:text-gray-700"
        >
          <span>{showBuiltIn ? "▾" : "▸"}</span>
          Built-in Rules <span className="font-normal">({builtIn.length})</span>
        </button>
        {showBuiltIn && (
          <div className="bg-white border border-gray-100 rounded-xl shadow-sm overflow-hidden">
            <table className="w-full text-sm">
              <tbody className="divide-y divide-gray-50">
                {builtIn.map((r) => (
                  <tr key={r.vendor_pattern} className="hover:bg-gray-50">
                    <td className="px-4 py-3 font-mono text-gray-400">{r.vendor_pattern}</td>
                    <td className="px-4 py-3 capitalize text-gray-400">{r.category}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  );
}
