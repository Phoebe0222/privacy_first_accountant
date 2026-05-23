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

      {summary.by_category.length > 0 && (
        <div className="bg-white rounded-xl shadow-sm border border-gray-100 p-6">
          <h3 className="font-semibold text-gray-700 mb-4">Expenses by Category</h3>
          <div className="space-y-2">
            {summary.by_category.map((c) => (
              <div key={c.category} className="flex justify-between text-sm">
                <span className="capitalize text-gray-600">{c.category}</span>
                <span className="font-medium text-red-500">{fmt(c.total)}</span>
              </div>
            ))}
          </div>
        </div>
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
