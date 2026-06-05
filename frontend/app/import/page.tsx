"use client";
import { useEffect, useRef, useState } from "react";
import { api, EmailAccount } from "@/lib/api";

const GMAIL_IMAP = { host: "imap.gmail.com", port: 993 };
const OUTLOOK_IMAP = { host: "outlook.office365.com", port: 993 };

const SYNC_JOBS_KEY = "pa_sync_jobs";
type SavedJob = { jobId: string; reimport: boolean };

function getSavedJobs(): Record<number, SavedJob> {
  try { return JSON.parse(localStorage.getItem(SYNC_JOBS_KEY) || "{}"); }
  catch { return {}; }
}
function persistJob(id: number, jobId: string, reimport: boolean) {
  const jobs = getSavedJobs();
  jobs[id] = { jobId, reimport };
  localStorage.setItem(SYNC_JOBS_KEY, JSON.stringify(jobs));
}
function removeJob(id: number) {
  const jobs = getSavedJobs();
  delete jobs[id];
  localStorage.setItem(SYNC_JOBS_KEY, JSON.stringify(jobs));
}

const CSV_JOB_KEY = "pa_csv_job";
type SavedCsvJob = { jobId: string; filename: string };

function getSavedCsvJob(): SavedCsvJob | null {
  try { return JSON.parse(localStorage.getItem(CSV_JOB_KEY) || "null"); }
  catch { return null; }
}
function persistCsvJob(jobId: string, filename: string) {
  localStorage.setItem(CSV_JOB_KEY, JSON.stringify({ jobId, filename }));
}
function removeCsvJob() {
  localStorage.removeItem(CSV_JOB_KEY);
}

const BANK_CSV_JOB_KEY = "pa_bank_csv_job";

function getSavedBankCsvJob(): SavedCsvJob | null {
  try { return JSON.parse(localStorage.getItem(BANK_CSV_JOB_KEY) || "null"); }
  catch { return null; }
}
function persistBankCsvJob(jobId: string, filename: string) {
  localStorage.setItem(BANK_CSV_JOB_KEY, JSON.stringify({ jobId, filename }));
}
function removeBankCsvJob() {
  localStorage.removeItem(BANK_CSV_JOB_KEY);
}

const FILE_JOB_KEY = "pa_file_job";

function getSavedFileJob(): string | null {
  return localStorage.getItem(FILE_JOB_KEY);
}
function persistFileJob(jobId: string) {
  localStorage.setItem(FILE_JOB_KEY, jobId);
}
function removeFileJob() {
  localStorage.removeItem(FILE_JOB_KEY);
}

export default function ImportPage() {
  const [accounts, setAccounts] = useState<EmailAccount[]>([]);
  const [showForm, setShowForm] = useState(false);
  const [syncing, setSyncing] = useState<number | null>(null);
  const [reimporting, setReimporting] = useState<number | null>(null);
  const [syncResult, setSyncResult] = useState<string>("");
  const [form, setForm] = useState({
    name: "", email: "", imap_host: "imap.gmail.com", imap_port: 993, username: "", password: "",
  });
  const [uploading, setUploading] = useState(false);
  const [uploadResult, setUploadResult] = useState<string>("");
  const fileRef = useRef<HTMLInputElement>(null);
  const csvRef = useRef<HTMLInputElement>(null);
  const [csvUploading, setCsvUploading] = useState(false);
  const [csvResult, setCsvResult] = useState<string>("");
  const [lastCsvFile, setLastCsvFile] = useState<string | null>(null);
  const bankCsvRef = useRef<HTMLInputElement>(null);
  const [bankCsvUploading, setBankCsvUploading] = useState(false);
  const [bankCsvResult, setBankCsvResult] = useState<string>("");
  const [lastBankCsvFile, setLastBankCsvFile] = useState<string | null>(null);
  const [importHistory, setImportHistory] = useState<{ source: string; source_ref: string; count: number; date_from: string; date_to: string; imported_at: string }[]>([]);

  function loadImportHistory() {
    api.getImportHistory().then(setImportHistory).catch(() => {});
  }

  function loadAccounts() {
    api.getEmailAccounts().then(setAccounts).catch(() => {});
  }

  async function resumePolling(id: number, jobId: string, reimport: boolean) {
    try {
      const r = await api.pollJob(jobId);
      setSyncResult(`Done: ${r.added} new transactions added, ${r.skipped} skipped.`);
      loadAccounts();
    } catch (e: unknown) {
      setSyncResult(`Error: ${e instanceof Error ? e.message : String(e)}`);
    } finally {
      removeJob(id);
      reimport ? setReimporting(null) : setSyncing(null);
    }
  }

  async function resumeCsvJob(jobId: string, filename: string) {
    setCsvUploading(true);
    setLastCsvFile(filename);
    try {
      const r = await api.pollJob(jobId);
      setCsvResult(`Done: ${r.added} transactions imported, ${r.skipped} rows skipped.`);
      loadImportHistory();
    } catch (e: unknown) {
      setCsvResult(`Error: ${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setCsvUploading(false);
      removeCsvJob();
    }
  }

  async function resumeBankCsvJob(jobId: string, filename: string) {
    setBankCsvUploading(true);
    setLastBankCsvFile(filename);
    try {
      const r = await api.pollJob(jobId);
      setBankCsvResult(`Done: ${r.added} transactions imported, ${r.skipped} rows skipped.`);
      loadImportHistory();
    } catch (e: unknown) {
      setBankCsvResult(`Error: ${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setBankCsvUploading(false);
      removeBankCsvJob();
    }
  }

  async function resumeFileJob(jobId: string) {
    setUploading(true);
    try {
      const t = await api.pollFileJob(jobId);
      setUploadResult(`Extracted: ${t.vendor} — ${t.type} of $${t.amount} on ${t.date} (${t.category})`);
    } catch (e: unknown) {
      setUploadResult(`Error: ${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setUploading(false);
      removeFileJob();
    }
  }

  useEffect(() => {
    loadAccounts();
    loadImportHistory();
    const saved = getSavedJobs();
    for (const [idStr, { jobId, reimport }] of Object.entries(saved)) {
      const id = Number(idStr);
      reimport ? setReimporting(id) : setSyncing(id);
      resumePolling(id, jobId, reimport);
    }
    const csvJob = getSavedCsvJob();
    if (csvJob) resumeCsvJob(csvJob.jobId, csvJob.filename);
    const bankCsvJob = getSavedBankCsvJob();
    if (bankCsvJob) resumeBankCsvJob(bankCsvJob.jobId, bankCsvJob.filename);
    const fileJobId = getSavedFileJob();
    if (fileJobId) resumeFileJob(fileJobId);
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  async function handleAddAccount(e: React.FormEvent) {
    e.preventDefault();
    await api.addEmailAccount(form);
    setShowForm(false);
    setForm({ name: "", email: "", imap_host: "imap.gmail.com", imap_port: 993, username: "", password: "" });
    loadAccounts();
  }

  async function handleSync(id: number, reimport = false) {
    reimport ? setReimporting(id) : setSyncing(id);
    setSyncResult("");
    let jobId: string;
    try {
      const res = await api.startSync(id, reimport);
      jobId = res.job_id;
    } catch (e: unknown) {
      setSyncResult(`Error: ${e instanceof Error ? e.message : String(e)}`);
      reimport ? setReimporting(null) : setSyncing(null);
      return;
    }
    persistJob(id, jobId, reimport);
    await resumePolling(id, jobId, reimport);
  }

  async function handleCsvUpload(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;
    if (csvRef.current) csvRef.current.value = "";
    setCsvUploading(true);
    setCsvResult("");
    setLastCsvFile(file.name);
    let jobId: string;
    try {
      const res = await api.startCsvUpload(file);
      jobId = res.job_id;
    } catch (err: unknown) {
      setCsvResult(`Error: ${err instanceof Error ? err.message : String(err)}`);
      setCsvUploading(false);
      return;
    }
    persistCsvJob(jobId, file.name);
    try {
      const r = await api.pollJob(jobId);
      setCsvResult(`Done: ${r.added} transactions imported, ${r.skipped} rows skipped.`);
      loadImportHistory();
    } catch (err: unknown) {
      setCsvResult(`Error: ${err instanceof Error ? err.message : String(err)}`);
    } finally {
      setCsvUploading(false);
      removeCsvJob();
    }
  }

  async function handleBankCsvUpload(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;
    if (bankCsvRef.current) bankCsvRef.current.value = "";
    setBankCsvUploading(true);
    setBankCsvResult("");
    setLastBankCsvFile(file.name);
    let jobId: string;
    try {
      const res = await api.startBankCsvUpload(file);
      jobId = res.job_id;
    } catch (err: unknown) {
      setBankCsvResult(`Error: ${err instanceof Error ? err.message : String(err)}`);
      setBankCsvUploading(false);
      return;
    }
    persistBankCsvJob(jobId, file.name);
    try {
      const r = await api.pollJob(jobId);
      setBankCsvResult(`Done: ${r.added} transactions imported, ${r.skipped} rows skipped.`);
      loadImportHistory();
    } catch (err: unknown) {
      setBankCsvResult(`Error: ${err instanceof Error ? err.message : String(err)}`);
    } finally {
      setBankCsvUploading(false);
      removeBankCsvJob();
    }
  }

  async function handleFileUpload(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;
    if (fileRef.current) fileRef.current.value = "";
    setUploading(true);
    setUploadResult("");
    let jobId: string;
    try {
      const res = await api.startFileUpload(file);
      jobId = res.job_id;
    } catch (err: unknown) {
      setUploadResult(`Error: ${err instanceof Error ? err.message : String(err)}`);
      setUploading(false);
      return;
    }
    persistFileJob(jobId);
    try {
      const t = await api.pollFileJob(jobId);
      setUploadResult(`Extracted: ${t.vendor} — ${t.type} of $${t.amount} on ${t.date} (${t.category})`);
    } catch (err: unknown) {
      setUploadResult(`Error: ${err instanceof Error ? err.message : String(err)}`);
    } finally {
      setUploading(false);
      removeFileJob();
    }
  }

  return (
    <div className="space-y-10 max-w-2xl">
      <h2 className="text-2xl font-bold text-gray-800">Import</h2>

      {/* Email accounts */}
      <section className="space-y-4">
        <div className="flex items-center justify-between">
          <h3 className="text-lg font-semibold text-gray-700">Email Accounts</h3>
          <button
            onClick={() => setShowForm(!showForm)}
            className="text-sm bg-blue-600 text-white px-4 py-2 rounded-lg hover:bg-blue-700 transition-colors"
          >
            + Add Account
          </button>
        </div>

        {showForm && (
          <form onSubmit={handleAddAccount} className="bg-white border border-gray-100 rounded-xl p-6 space-y-4 shadow-sm">
            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className="text-xs text-gray-500 mb-1 block">Account name</label>
                <input required value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })}
                  placeholder="e.g. Work Gmail" className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm" />
              </div>
              <div>
                <label className="text-xs text-gray-500 mb-1 block">Email address</label>
                <input required type="email" value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })}
                  className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm" />
              </div>
            </div>
            <div className="flex gap-3">
              <button type="button" onClick={() => setForm({ ...form, ...GMAIL_IMAP })}
                className="text-xs border border-gray-200 rounded px-3 py-1.5 hover:bg-gray-50">Gmail</button>
              <button type="button" onClick={() => setForm({ ...form, ...OUTLOOK_IMAP })}
                className="text-xs border border-gray-200 rounded px-3 py-1.5 hover:bg-gray-50">Outlook</button>
            </div>
            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className="text-xs text-gray-500 mb-1 block">IMAP host</label>
                <input required value={form.imap_host} onChange={(e) => setForm({ ...form, imap_host: e.target.value })}
                  className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm" />
              </div>
              <div>
                <label className="text-xs text-gray-500 mb-1 block">Port</label>
                <input required type="number" value={form.imap_port} onChange={(e) => setForm({ ...form, imap_port: Number(e.target.value) })}
                  className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm" />
              </div>
            </div>
            <div>
              <label className="text-xs text-gray-500 mb-1 block">Username (usually your email)</label>
              <input required value={form.username} onChange={(e) => setForm({ ...form, username: e.target.value })}
                className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm" />
            </div>
            <div>
              <label className="text-xs text-gray-500 mb-1 block">App password</label>
              <input required type="password" value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })}
                className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm" />
              <p className="text-xs text-gray-400 mt-1">Gmail: use an App Password, not your main password.</p>
            </div>
            <div className="flex gap-3 pt-2">
              <button type="submit" className="bg-blue-600 text-white px-5 py-2 rounded-lg text-sm hover:bg-blue-700">Save</button>
              <button type="button" onClick={() => setShowForm(false)} className="text-sm text-gray-500 hover:text-gray-700">Cancel</button>
            </div>
          </form>
        )}

        {accounts.length === 0 && !showForm && (
          <p className="text-gray-400 text-sm">No email accounts connected yet.</p>
        )}
        <div className="space-y-3">
          {accounts.map((a) => (
            <div key={a.id} className="bg-white border border-gray-100 rounded-xl p-4 flex items-center justify-between shadow-sm">
              <div>
                <p className="font-medium text-gray-800">{a.name}</p>
                <p className="text-sm text-gray-400">{a.email} · {a.imap_host}</p>
                {a.last_synced && <p className="text-xs text-gray-300 mt-0.5">Last synced: {new Date(a.last_synced).toLocaleString()}</p>}
              </div>
              <div className="flex gap-2">
                <button
                  onClick={() => handleSync(a.id)}
                  disabled={syncing === a.id || reimporting === a.id}
                  className="text-sm bg-gray-800 text-white px-4 py-2 rounded-lg hover:bg-gray-700 disabled:opacity-50"
                >
                  {syncing === a.id ? "Syncing…" : "Sync"}
                </button>
                <button
                  onClick={() => handleSync(a.id, true)}
                  disabled={syncing === a.id || reimporting === a.id}
                  className="text-sm border border-gray-300 text-gray-600 px-4 py-2 rounded-lg hover:bg-gray-50 disabled:opacity-50"
                >
                  {reimporting === a.id ? "Re-importing…" : "Re-import"}
                </button>
                <button onClick={() => api.deleteEmailAccount(a.id).then(loadAccounts)}
                  className="text-sm text-gray-300 hover:text-red-500 px-2">✕</button>
              </div>
            </div>
          ))}
        </div>
        {syncResult && (
          <p className={`text-sm ${syncResult.startsWith("Error") ? "text-red-500" : "text-green-600"}`}>{syncResult}</p>
        )}
      </section>

      {/* CSV upload */}
      {/* ── Bank Statement CSV ── */}
      <section className="space-y-4">
        <div className="flex items-center justify-between">
          <div>
            <h3 className="text-lg font-semibold text-gray-700">Bank Statement CSV</h3>
            <p className="text-xs text-gray-400 mt-0.5">ANZ, CommBank, Westpac, NAB — used for reconciliation</p>
          </div>
          <button
            onClick={async () => {
              if (!confirm("Delete ALL bank CSV transactions? This cannot be undone.")) return;
              try {
                const r = await api.deleteBySource("bank_csv");
                setBankCsvResult(`Removed ${r.deleted} bank transactions.`);
                setLastBankCsvFile(null);
              } catch (e: unknown) {
                setBankCsvResult(`Error: ${e instanceof Error ? e.message : String(e)}`);
              }
            }}
            className="text-xs text-red-400 hover:text-red-600 underline"
          >Clear all</button>
        </div>
        <div className="bg-white border-2 border-dashed border-gray-200 rounded-xl p-8 text-center">
          <input ref={bankCsvRef} type="file" accept=".csv,.xlsx,.xls" onChange={handleBankCsvUpload} className="hidden" id="bank-csv-upload" />
          <label htmlFor="bank-csv-upload"
            className="cursor-pointer bg-gray-800 text-white px-5 py-2 rounded-lg text-sm hover:bg-gray-700 transition-colors">
            {bankCsvUploading ? "Processing…" : "Choose Bank Statement CSV"}
          </label>
        </div>
        {bankCsvResult && (
          <div className="flex items-center gap-3">
            <p className={`text-sm ${bankCsvResult.startsWith("Error") ? "text-red-500" : "text-green-600"}`}>{bankCsvResult}</p>
            {lastBankCsvFile && !bankCsvResult.startsWith("Error") && (
              <button
                onClick={async () => {
                  if (!confirm(`Remove all transactions imported from "${lastBankCsvFile}"?`)) return;
                  try {
                    const r = await api.deleteBySourceRef(lastBankCsvFile);
                    setBankCsvResult(`Removed ${r.deleted} transactions from "${lastBankCsvFile}".`);
                    setLastBankCsvFile(null);
                  } catch (e: unknown) {
                    setBankCsvResult(`Error: ${e instanceof Error ? e.message : String(e)}`);
                  }
                }}
                className="text-xs text-red-400 hover:text-red-600 underline whitespace-nowrap"
              >Remove import</button>
            )}
          </div>
        )}
      </section>

      {/* ── Receipt / Marketplace CSV ── */}
      <section className="space-y-4">
        <div className="flex items-center justify-between">
          <div>
            <h3 className="text-lg font-semibold text-gray-700">Receipt / Marketplace CSV</h3>
            <p className="text-xs text-gray-400 mt-0.5">PayPal, Stripe, Etsy, Shopify — treated as receipts</p>
          </div>
          <button
            onClick={async () => {
              if (!confirm("Delete ALL receipt CSV transactions? This cannot be undone.")) return;
              try {
                const r = await api.deleteBySource("csv");
                setCsvResult(`Removed ${r.deleted} CSV transactions.`);
                setLastCsvFile(null);
              } catch (e: unknown) {
                setCsvResult(`Error: ${e instanceof Error ? e.message : String(e)}`);
              }
            }}
            className="text-xs text-red-400 hover:text-red-600 underline"
          >
            Clear all CSV
          </button>
        </div>
        <div className="bg-white border-2 border-dashed border-gray-200 rounded-xl p-8 text-center">
          <input ref={csvRef} type="file" accept=".csv,.xlsx,.xls" onChange={handleCsvUpload} className="hidden" id="csv-upload" />
          <label htmlFor="csv-upload"
            className="cursor-pointer bg-blue-600 text-white px-5 py-2 rounded-lg text-sm hover:bg-blue-700 transition-colors">
            {csvUploading ? "Processing…" : "Choose CSV"}
          </label>
        </div>
        {csvResult && (
          <div className="flex items-center gap-3">
            <p className={`text-sm ${csvResult.startsWith("Error") ? "text-red-500" : "text-green-600"}`}>{csvResult}</p>
            {lastCsvFile && !csvResult.startsWith("Error") && (
              <button
                onClick={async () => {
                  if (!confirm(`Remove all transactions imported from "${lastCsvFile}"?`)) return;
                  try {
                    const r = await api.deleteBySourceRef(lastCsvFile);
                    setCsvResult(`Removed ${r.deleted} transactions from "${lastCsvFile}".`);
                    setLastCsvFile(null);
                  } catch (e: unknown) {
                    setCsvResult(`Error: ${e instanceof Error ? e.message : String(e)}`);
                  }
                }}
                className="text-xs text-red-400 hover:text-red-600 underline whitespace-nowrap"
              >
                Remove import
              </button>
            )}
          </div>
        )}
      </section>

      {/* File upload */}
      <section className="space-y-4">
        <h3 className="text-lg font-semibold text-gray-700">Upload PDF or Receipt Photo</h3>
        <div className="bg-white border-2 border-dashed border-gray-200 rounded-xl p-8 text-center">
          <p className="text-gray-400 text-sm mb-4">PDF invoices, receipt images (JPG, PNG, WEBP)</p>
          <input ref={fileRef} type="file" accept=".pdf,.jpg,.jpeg,.png,.webp"
            onChange={handleFileUpload} className="hidden" id="file-upload" />
          <label htmlFor="file-upload"
            className="cursor-pointer bg-blue-600 text-white px-5 py-2 rounded-lg text-sm hover:bg-blue-700 transition-colors">
            {uploading ? "Processing…" : "Choose File"}
          </label>
        </div>
        {uploadResult && (
          <p className={`text-sm ${uploadResult.startsWith("Error") ? "text-red-500" : "text-green-600"}`}>{uploadResult}</p>
        )}
      </section>

      {/* ── Import History (all sources) ── */}
      {importHistory.length > 0 && (
        <div className="space-y-2">
          <h4 className="text-sm font-medium text-gray-500">Import History</h4>
          <div className="bg-white border border-gray-100 rounded-xl shadow-sm overflow-hidden">
            <table className="w-full text-sm">
              <tbody className="divide-y divide-gray-50">
                {importHistory.map((h) => (
                  <tr key={h.source_ref} className="hover:bg-gray-50">
                    <td className="px-4 py-3">
                      <p className="font-medium text-gray-700 truncate max-w-xs">{h.source_ref}</p>
                      <p className="text-xs text-gray-400">{h.date_from} — {h.date_to}</p>
                    </td>
                    <td className="px-4 py-3 text-gray-400 text-xs">
                      <span className={`px-1.5 py-0.5 rounded text-xs ${h.source === "bank_csv" ? "bg-gray-100 text-gray-600" : "bg-blue-50 text-blue-600"}`}>
                        {h.source === "bank_csv" ? "Bank CSV" : h.source}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-gray-400 text-xs">{h.count} transactions</td>
                    <td className="px-4 py-3 text-right">
                      <button
                        onClick={async () => {
                          if (!confirm(`Remove all ${h.count} transactions from "${h.source_ref}"?`)) return;
                          try {
                            const r = await api.deleteBySourceRef(h.source_ref);
                            setCsvResult(`Removed ${r.deleted} transactions from "${h.source_ref}".`);
                            loadImportHistory();
                          } catch (e: unknown) {
                            setCsvResult(`Error: ${e instanceof Error ? e.message : String(e)}`);
                          }
                        }}
                        className="text-xs text-gray-300 hover:text-red-500 transition-colors"
                      >Remove</button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}
