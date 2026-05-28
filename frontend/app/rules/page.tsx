"use client";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";

const CATEGORIES = ["food", "grocery", "cafe", "transport", "travel", "utilities", "software", "marketing", "revenue", "salary", "refund", "office", "subscription", "shopping", "leisure", "material", "fee", "gym", "medical", "other"];

type VendorRule = { id: number; vendor_pattern: string; category: string };
type BuiltInRule = { vendor_pattern: string; category: string };
type ATORule = { id: number; title: string; description: string };
type Tab = "vendor" | "ato";

export default function RulesPage() {
  const [tab, setTab] = useState<Tab>("vendor");

  return (
    <div className="space-y-6 max-w-2xl">
      <h2 className="text-2xl font-bold text-gray-800">Rules</h2>

      <div className="flex border-b border-gray-200">
        {([["vendor", "Vendor Rules"], ["ato", "ATO Rules"]] as [Tab, string][]).map(([t, label]) => (
          <button
            key={t}
            onClick={() => setTab(t)}
            className={`px-5 py-2.5 text-sm font-medium border-b-2 -mb-px transition-colors ${
              tab === t ? "border-blue-600 text-blue-600" : "border-transparent text-gray-500 hover:text-gray-700"
            }`}
          >
            {label}
          </button>
        ))}
      </div>

      {tab === "vendor" && <VendorRulesTab />}
      {tab === "ato" && <ATORulesTab />}
    </div>
  );
}

function VendorRulesTab() {
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
        Matching is case-insensitive substring — e.g. <code className="bg-gray-100 px-1 rounded">aws</code> matches <em>Amazon AWS Invoice</em>.
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
          <select value={category} onChange={(e) => setCategory(e.target.value)}
            className="border border-gray-200 rounded-lg px-3 py-2 text-sm bg-white">
            {CATEGORIES.map((c) => <option key={c} value={c}>{c}</option>)}
          </select>
          <button type="submit" className="bg-blue-600 text-white px-4 py-2 rounded-lg text-sm hover:bg-blue-700">Add</button>
        </div>
        {error && <p className="text-red-500 text-sm">{error}</p>}
      </form>

      <section className="space-y-3">
        <h3 className="font-semibold text-gray-700">Custom Rules <span className="text-gray-400 font-normal">({rules.length})</span></h3>
        {rules.length === 0 ? (
          <p className="text-sm text-gray-400">No custom rules yet.</p>
        ) : (
          <RuleTable rows={rules} onDelete={(id) => api.deleteVendorRule(id).then(load)}>
            {(r) => <><td className="px-4 py-3 font-mono text-gray-700">{r.vendor_pattern}</td><td className="px-4 py-3 capitalize text-gray-500">{r.category}</td></>}
          </RuleTable>
        )}
      </section>

      <section className="space-y-3">
        <button onClick={() => setShowBuiltIn((v) => !v)}
          className="flex items-center gap-2 text-sm font-semibold text-gray-500 hover:text-gray-700">
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

function ATORulesTab() {
  const [rules, setRules] = useState<ATORule[]>([]);
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [error, setError] = useState("");

  function load() { api.getATORules().then(setRules).catch(() => {}); }
  useEffect(() => { load(); }, []);

  async function handleAdd(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    try {
      await api.createATORule(title.trim(), description.trim());
      setTitle("");
      setDescription("");
      load();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to save rule");
    }
  }

  return (
    <div className="space-y-8">
      <p className="text-sm text-gray-500">
        Add Australian tax rules, thresholds, or deduction notes. These are injected into the chat AI so it can reference them when answering tax questions.
      </p>

      <form onSubmit={handleAdd} className="bg-white border border-gray-100 rounded-xl p-6 shadow-sm space-y-4">
        <h3 className="font-semibold text-gray-700">Add Rule</h3>
        <input
          required
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          placeholder="Title, e.g. GST Registration Threshold"
          className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm"
        />
        <textarea
          required
          value={description}
          onChange={(e) => setDescription(e.target.value)}
          placeholder="Description, e.g. Businesses with annual turnover ≥ $75,000 must register for GST."
          rows={3}
          className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm resize-none"
        />
        {error && <p className="text-red-500 text-sm">{error}</p>}
        <button type="submit" className="bg-blue-600 text-white px-4 py-2 rounded-lg text-sm hover:bg-blue-700">Add</button>
      </form>

      <section className="space-y-3">
        <h3 className="font-semibold text-gray-700">Custom ATO Rules <span className="text-gray-400 font-normal">({rules.length})</span></h3>
        {rules.length === 0 ? (
          <p className="text-sm text-gray-400">No ATO rules yet.</p>
        ) : (
          <RuleTable rows={rules} onDelete={(id) => api.deleteATORule(id).then(load)}>
            {(r) => <><td className="px-4 py-3 font-medium text-gray-700">{r.title}</td><td className="px-4 py-3 text-gray-500 text-xs">{r.description}</td></>}
          </RuleTable>
        )}
      </section>
    </div>
  );
}

function RuleTable<T extends { id: number }>({
  rows, onDelete, children,
}: {
  rows: T[];
  onDelete: (id: number) => void;
  children: (row: T) => React.ReactNode;
}) {
  return (
    <div className="bg-white border border-gray-100 rounded-xl shadow-sm overflow-hidden">
      <table className="w-full text-sm">
        <tbody className="divide-y divide-gray-50">
          {rows.map((r) => (
            <tr key={r.id} className="hover:bg-gray-50">
              {children(r)}
              <td className="px-4 py-3 text-right">
                <button onClick={() => onDelete(r.id)} className="text-gray-300 hover:text-red-500 text-xs transition-colors">
                  Delete
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
