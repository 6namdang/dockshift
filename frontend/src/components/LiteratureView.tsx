/**
 * @license
 * SPDX-License-Identifier: Apache-2.0
 */

import React, { useState, useEffect } from 'react';
import {
  Search,
  BookOpen,
  ExternalLink,
  Clock,
  Sparkles,
  ChevronDown,
  ChevronUp,
  Filter,
  CheckCircle2,
  FileText
} from 'lucide-react';
import { LiteraturePaper } from '../types/docking';
import { dockingService } from '../services/dockingService';

export const LiteratureView: React.FC = () => {
  const [query, setQuery] = useState('telomerase inhibitor');
  const [maxPerSource, setMaxPerSource] = useState(6);
  const [sources, setSources] = useState<string[]>([
    'pubmed',
    'biorxiv',
    'chemrxiv',
    'pubchem'
  ]);
  const [papers, setPapers] = useState<LiteraturePaper[]>([]);
  const [totalHits, setTotalHits] = useState<Record<string, number>>({});
  const [source, setSource] = useState<'backend' | 'demo'>('demo');
  const [isLoading, setIsLoading] = useState(false);
  const [expandedPapers, setExpandedPapers] = useState<Record<string, boolean>>({});

  const availableSources = [
    { id: 'pubmed', label: 'PubMed' },
    { id: 'biorxiv', label: 'bioRxiv' },
    { id: 'chemrxiv', label: 'ChemRxiv' },
    { id: 'patents', label: 'Patents' },
    { id: 'pubchem', label: 'PubChem' }
  ];

  const handleToggleSource = (srcId: string) => {
    setSources((prev) =>
      prev.includes(srcId) ? prev.filter((s) => s !== srcId) : [...prev, srcId]
    );
  };

  const handleSearch = async (e?: React.FormEvent) => {
    if (e) e.preventDefault();
    if (!query.trim()) return;

    setIsLoading(true);
    try {
      const resp = await dockingService.searchLiterature(query, sources, maxPerSource);
      setPapers(resp.results);
      setSource(resp.source);
      if (resp.totalHits) setTotalHits(resp.totalHits);
      else setTotalHits({});
    } catch (err) {
      console.error('Literature search error:', err);
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    handleSearch();
  }, []);

  const toggleAbstract = (id: string) => {
    setExpandedPapers((prev) => ({
      ...prev,
      [id]: !prev[id]
    }));
  };

  return (
    <div className="h-full flex flex-col bg-[#0C1423] text-[#F2F7FF] overflow-y-auto select-none">
      {/* Header */}
      <div className="px-6 py-4 border-b border-[#1c2e4a] bg-[#0E1728]/90 flex flex-wrap items-center justify-between gap-4">
        <div>
          <div className="flex items-center gap-2">
            <Search className="w-5 h-5 text-[#63E6DE]" />
            <h1 className="text-lg font-bold tracking-tight text-[#F2F7FF]">
              Scientific Literature Explorer
            </h1>
            <span className="px-2 py-0.5 text-xs font-mono rounded bg-[#1c2e4a] text-[#63E6DE] border border-[#63E6DE]/20">
              Multi-Source Pipeline
            </span>
            {source === 'demo' && (
              <span className="px-2 py-0.5 text-xs font-mono rounded bg-amber-950/60 text-[#E6A845] border border-[#E6A845]/30">
                Demonstration data — backend not connected
              </span>
            )}
          </div>
          <p className="text-xs text-[#91A6BE] mt-0.5">
            PubMed, bioRxiv, ChemRxiv, patents, and PubChem integrated query baseline.
          </p>
        </div>

        <div className="text-xs font-mono text-[#5E7594]">
          {papers.length} articles retrieved
        </div>
      </div>

      <div className="p-6 max-w-5xl mx-auto w-full space-y-6">
        {/* Search Bar & Options */}
        <section className="p-5 rounded-2xl bg-[#152237] border border-[#1e3250] shadow-md space-y-4">
          <form onSubmit={handleSearch} className="flex flex-wrap items-center gap-3">
            <div className="relative flex-1 min-w-[280px]">
              <Search className="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2 text-[#5E7594]" />
              <input
                type="text"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="e.g., hTERT inhibitor structure-activity, BIBR1532 allosteric pocket..."
                className="w-full pl-9 pr-3 py-2 bg-[#0C1423] border border-[#1e3250] rounded-xl text-xs font-mono text-[#F2F7FF] placeholder-[#5E7594] outline-none focus:border-[#63E6DE]"
              />
            </div>

            <div className="flex items-center gap-2">
              <label htmlFor="max-per-source" className="text-xs font-mono text-[#91A6BE]">
                Per source:
              </label>
              <input
                id="max-per-source"
                type="number"
                min={1}
                max={25}
                value={maxPerSource}
                onChange={(e) => setMaxPerSource(Math.max(1, Math.min(25, parseInt(e.target.value) || 6)))}
                className="w-16 px-2.5 py-2 rounded-xl bg-[#0C1423] border border-[#1e3250] text-xs font-mono text-[#F2F7FF] outline-none"
              />
            </div>

            <button
              type="submit"
              disabled={isLoading}
              className="px-4 py-2 rounded-xl bg-[#438DFF] hover:bg-[#347ce6] text-white text-xs font-mono font-bold transition flex items-center gap-1.5 shadow-md disabled:opacity-50"
            >
              {isLoading ? (
                <>
                  <Clock className="w-3.5 h-3.5 animate-spin" />
                  <span>Searching…</span>
                </>
              ) : (
                <>
                  <Search className="w-3.5 h-3.5" />
                  <span>Search</span>
                </>
              )}
            </button>
          </form>

          {/* Sources Checkboxes */}
          <div className="flex flex-wrap items-center gap-4 pt-2 border-t border-[#1c2e4a] text-xs font-mono">
            <span className="text-[#91A6BE]">Sources:</span>
            {availableSources.map((src) => {
              const isChecked = sources.includes(src.id);
              return (
                <label
                  key={src.id}
                  className="flex items-center gap-1.5 cursor-pointer text-[#F2F7FF]"
                >
                  <input
                    type="checkbox"
                    checked={isChecked}
                    onChange={() => handleToggleSource(src.id)}
                    className="accent-[#63E6DE]"
                  />
                  <span>{src.label}</span>
                </label>
              );
            })}
          </div>

          {/* Hits Summary */}
          {Object.keys(totalHits).length > 0 && (
            <div className="flex flex-wrap gap-3 pt-2 text-[11px] font-mono text-[#5E7594]">
              <span>Matches:</span>
              {Object.entries(totalHits).map(([k, v]) => (
                <span key={k} className="text-[#91A6BE]">
                  {k}: <strong className="text-[#63E6DE]">{v}</strong>
                </span>
              ))}
            </div>
          )}
        </section>

        {/* Papers List */}
        <section className="space-y-3">
          {papers.map((p) => {
            const isOpen = expandedPapers[p.id];
            return (
              <div
                key={p.id}
                className="p-5 rounded-2xl bg-[#152237] border border-[#1e3250] hover:border-[#1c2e4a] transition space-y-2.5"
              >
                <div className="flex items-start justify-between gap-3">
                  <h3 className="font-bold text-sm text-[#F2F7FF] leading-snug">
                    {p.url ? (
                      <a
                        href={p.url}
                        target="_blank"
                        rel="noreferrer"
                        className="hover:text-[#63E6DE] transition flex items-start gap-1.5"
                      >
                        <span>{p.title}</span>
                        <ExternalLink className="w-3.5 h-3.5 flex-shrink-0 mt-0.5 text-[#5E7594]" />
                      </a>
                    ) : (
                      p.title
                    )}
                  </h3>

                  <span className="px-2 py-0.5 text-[10px] font-mono rounded-full bg-[#0C1423] text-[#63E6DE] border border-[#1e3250] uppercase flex-shrink-0">
                    {p.source}
                  </span>
                </div>

                {/* Metadata */}
                <div className="flex flex-wrap items-center gap-3 text-xs font-mono text-[#91A6BE]">
                  {p.published_date && <span>Year: {p.published_date}</span>}
                  {p.venue && <span>• {p.venue}</span>}
                  {p.confidence !== undefined && (
                    <span className="text-emerald-400">
                      • match {(p.confidence * 100).toFixed(0)}%
                    </span>
                  )}
                  {p.doi && (
                    <a
                      href={`https://doi.org/${p.doi}`}
                      target="_blank"
                      rel="noreferrer"
                      className="text-[#438DFF] hover:underline"
                    >
                      DOI: {p.doi}
                    </a>
                  )}
                </div>

                {/* Authors */}
                {p.authors && p.authors.length > 0 && (
                  <div className="text-xs text-[#5E7594]">
                    Authors: {p.authors.join(', ')}
                  </div>
                )}

                {/* Abstract */}
                {p.abstract && (
                  <div className="space-y-1 pt-1">
                    <p
                      className={`text-xs text-[#91A6BE] leading-relaxed ${
                        isOpen ? '' : 'line-clamp-3'
                      }`}
                    >
                      {p.abstract}
                    </p>
                    <button
                      onClick={() => toggleAbstract(p.id)}
                      className="text-[11px] font-mono text-[#438DFF] hover:underline flex items-center gap-1"
                    >
                      {isOpen ? 'Show less' : 'Show full abstract'}
                      {isOpen ? <ChevronUp className="w-3 h-3" /> : <ChevronDown className="w-3 h-3" />}
                    </button>
                  </div>
                )}
              </div>
            );
          })}
        </section>
      </div>
    </div>
  );
};
