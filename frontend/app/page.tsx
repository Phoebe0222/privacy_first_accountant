"use client";
import { useEffect, useState } from "react";
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer,
} from "recharts";
import { api, Summary } from "@/lib/api";

function StatCard({ label, value, color }: { label: string; value: string; color: string }) {
  return (
    <div className="bg-white rounded-xl shadow-sm border border-gray-100 p-6">
      <p className="text-sm text-gray-500">{label}</p>
      <p className={`text-3xl font-bold mt-1 ${color}`}>{value}</p>
    </div>
  );
}

function fmt(n: number) {
  return new Intl.NumberFormat("en-AU", { style: "currency", currency: "AUD" }).format(n);
}

export default function Dashboard() {
  const [summary, setSummary] = useState<Summary | null>(null);
  const [error, setError] = useState("");
  const [bizTab, setBizTab] = useState<"expenses" | "income">("expenses");
  const [empTab, setEmpTab] = useState<"expenses" | "income">("expenses");
  const [personalTab, setPersonalTab] = useState<"expenses" | "income">("expenses");

  useEffect(() => {
    api.getSummary().then(setSummary).catch(() => setError("Could not connect to backend."));
  }, []);

  if (error) return <div className="text-red-500 mt-8">{error} Make sure the API is running.</div>;
  if (!summary) return <div className="text-gray-400 mt-8">Loading…</div>;

  const chartData = buildChartData(summary.monthly);

  return (
    <div className="space-y-8">
      <h2 className="text-2xl font-bold text-gray-800">Dashboard</h2>

      <div className="grid grid-cols-3 gap-6">
        <StatCard label="Total Revenue" value={fmt(summary.total_income)} color="text-green-600" />
        <StatCard label="Total Expenses" value={fmt(summary.total_expenses)} color="text-red-500" />
        <StatCard
          label="Net Profit"
          value={fmt(summary.net_profit)}
          color={summary.net_profit >= 0 ? "text-blue-600" : "text-red-600"}
        />
      </div>

      <div className="bg-white rounded-xl shadow-sm border border-gray-100 p-6">
        <h3 className="font-semibold text-gray-700 mb-4">Monthly Cash Flow</h3>
        {chartData.length === 0 ? (
          <p className="text-gray-400 text-sm">No data yet — import some transactions to get started.</p>
        ) : (
          <ResponsiveContainer width="100%" height={280}>
            <BarChart data={chartData}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis dataKey="month" />
              <YAxis tickFormatter={(v) => `$${(v / 1000).toFixed(0)}k`} />
              <Tooltip formatter={(v) => fmt(v as number)} />
              <Legend />
              <Bar dataKey="income" fill="#22c55e" name="Revenue" />
              <Bar dataKey="expenses" fill="#ef4444" name="Expenses" />
            </BarChart>
          </ResponsiveContainer>
        )}
      </div>

      <div className="grid grid-cols-3 gap-6">
        {/* Business */}
        <SummaryBoard title="Business"
          stats={[
            { label: "Revenue", value: fmt(summary.business_income), color: "text-green-600" },
            { label: "Costs",   value: fmt(summary.business_expenses), color: "text-red-500" },
            { label: "Net",     value: fmt(summary.business_net), color: summary.business_net >= 0 ? "text-blue-600" : "text-red-600" },
          ]}
          tab={bizTab} onTab={setBizTab}
          expenseRows={summary.by_category_business}
          incomeRows={summary.by_category_business_income}
          emptyExpense="No business expenses yet — mark transactions as Business in Transactions."
          emptyIncome="No business income yet."
        />

        {/* Employment */}
        <SummaryBoard title="Employment"
          stats={[
            { label: "Salary", value: fmt(summary.employment_income), color: "text-green-600" },
            { label: "Costs",  value: fmt(summary.employment_expenses), color: "text-red-500" },
          ]}
          tab={empTab} onTab={setEmpTab}
          expenseRows={summary.by_category_employment}
          incomeRows={summary.by_category_employment_income}
          emptyExpense="No employment expenses yet."
          emptyIncome="No employment income yet."
        />

        {/* Personal */}
        <SummaryBoard title="Personal"
          stats={[
            { label: "Spending", value: fmt(summary.personal_expenses), color: "text-red-500" },
            { label: "Income",   value: fmt(summary.personal_income), color: "text-green-600" },
          ]}
          tab={personalTab} onTab={setPersonalTab}
          expenseRows={summary.by_category_personal}
          incomeRows={summary.by_category_personal_income}
          emptyExpense="No personal expenses yet."
          emptyIncome="No personal income yet."
        />
      </div>
    </div>
  );
}

function SummaryBoard({ title, stats, tab, onTab, expenseRows, incomeRows, emptyExpense, emptyIncome }: {
  title: string;
  stats: { label: string; value: string; color: string }[];
  tab: "expenses" | "income";
  onTab: (t: "expenses" | "income") => void;
  expenseRows: { category: string; total: number }[];
  incomeRows: { category: string; total: number }[];
  emptyExpense: string;
  emptyIncome: string;
}) {
  const rows = tab === "expenses" ? expenseRows : incomeRows;
  return (
    <div className="bg-white rounded-xl shadow-sm border border-gray-100 p-6 space-y-4">
      <h3 className="font-semibold text-gray-700">{title}</h3>
      <div className={`grid grid-cols-${stats.length} gap-3 text-center`}>
        {stats.map((s) => (
          <div key={s.label}>
            <p className="text-xs text-gray-400">{s.label}</p>
            <p className={`text-lg font-bold ${s.color}`}>{s.value}</p>
          </div>
        ))}
      </div>
      <div className="flex gap-2 pt-1">
        {(["expenses", "income"] as const).map((t) => (
          <button key={t} onClick={() => onTab(t)}
            className={`text-xs px-3 py-1 rounded-full border transition-colors ${tab === t ? "bg-gray-800 text-white border-gray-800" : "text-gray-500 border-gray-200 hover:border-gray-400"}`}>
            {t === "expenses" ? "Costs" : "Income"}
          </button>
        ))}
      </div>
      {rows.length > 0 ? (
        <div className="space-y-1.5 pt-2 border-t border-gray-50">
          {[...rows].sort((a, b) => b.total - a.total).map((c) => (
            <div key={c.category} className="flex justify-between text-sm">
              <span className="capitalize text-gray-500">{c.category.replace("_", " ")}</span>
              <span className="font-medium text-gray-700">{fmt(c.total)}</span>
            </div>
          ))}
        </div>
      ) : (
        <p className="text-xs text-gray-400 pt-2 border-t border-gray-50">
          {tab === "expenses" ? emptyExpense : emptyIncome}
        </p>
      )}
    </div>
  );
}

function buildChartData(monthly: Summary["monthly"]) {
  const map: Record<string, { month: string; income: number; expenses: number }> = {};
  for (const row of monthly) {
    if (!map[row.month]) map[row.month] = { month: row.month, income: 0, expenses: 0 };
    if (row.type === "income") map[row.month].income = row.total;
    else map[row.month].expenses = row.total;
  }
  return Object.values(map).sort((a, b) => a.month.localeCompare(b.month));
}
