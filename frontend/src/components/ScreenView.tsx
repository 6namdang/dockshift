/**
 * @license
 * SPDX-License-Identifier: Apache-2.0
 */

import React, { useState } from 'react';
import {
  Crosshair,
  Play,
  Clock,
  ExternalLink,
  CheckCircle2,
  AlertTriangle,
  Info,
  Sliders,
  Sparkles,
  ArrowRight,
  Shield,
  Layers,
  ChevronDown,
  ChevronUp
} from 'lucide-react';
import { Ligand, Protein } from '../types/docking';

interface ScreenViewProps {
  protein: Protein;
  candidates: Ligand[];
  selectedCandidateId: string;
  onSelectCandidate: (id: string) => void;
  onExploreInPlayground: (candidateId: string) => void;
  onRunScreening: (count: number) => Promise<void>;
  isLoadingScreening: boolean;
  source?: 'backend' | 'demo';
}

export const ScreenView: React.FC<ScreenViewProps> = ({
  protein,
  candidates,
  selectedCandidateId,
  onSelectCandidate,
  onExploreInPlayground,
  onRunScreening,
  isLoadingScreening,
  source = 'demo'
}) => {
  const [shortlistCount, setShortlistCount] = useState<number>(6);
  const [hasRun, setHasRun] = useState<boolean>(true);
  const [showTableView, setShowTableView] = useState<boolean>(false);
  const [hoveredPoint, setHoveredPoint] = useState<{
    candidate: Ligand;
    type: 'pred' | 'meas';
    x: number;
    y: number;
  } | null>(null);

  const AXIS = { min: 4.0, max: 8.5, ticks: [4.0, 5.0, 6.0, 7.0, 8.0] };
  const pos = (val: number) => {
    const clamped = Math.min(Math.max(val, AXIS.min), AXIS.max);
    return ((clamped - AXIS.min) / (AXIS.max - AXIS.min)) * 100;
  };

  const handleRun = async () => {
    await onRunScreening(shortlistCount);
    setHasRun(true);
  };

  const scoredCandidates = candidates.filter(
    (c) => c.prediction?.predicted_pic50 != null
  );

  return (
    <div className="h-full flex flex-col bg-[#0D1619] text-[#F2F7FF] overflow-y-auto select-none">
      {/* View Header */}
      <div className="px-6 py-4 border-b border-[#1B292D] bg-[#0A1214] flex flex-wrap items-center justify-between gap-4">
        <div>
          <div className="flex items-center gap-2">
            <Crosshair className="w-5 h-5 text-[#4EBEA4]" />
            <h1 className="text-lg font-bold tracking-tight text-[#F2F7FF]">
              QSAR Candidate Screening Workflow
            </h1>
            <span className="px-2 py-0.5 text-xs font-mono rounded bg-[#152328] text-[#4EBEA4] border border-[#4EBEA4]/30">
              Inhibitor Shortlisting Baseline
            </span>
            {source === 'demo' && (
              <span className="px-2 py-0.5 text-xs font-mono rounded bg-amber-950/60 text-[#E6A845] border border-[#E6A845]/30">
                Demonstration data — backend not connected
              </span>
            )}
          </div>
          <p className="text-xs text-[#859CA6] mt-0.5">
            Select target, screen candidate molecules using machine-learning QSAR models, and rank by predicted potency.
          </p>
        </div>

        <div className="flex items-center gap-2 text-xs font-mono text-[#556F7A]">
          <span>Model: Iraqui &amp; Dang (2026)</span>
          <span>•</span>
          <a
            href="https://doi.org/10.26434/chemrxiv.15005669/v2"
            target="_blank"
            rel="noreferrer"
            className="text-[#4EBEA4] hover:underline flex items-center gap-1"
          >
            ChemRxiv 10.26434
            <ExternalLink className="w-3 h-3" />
          </a>
        </div>
      </div>

      <div className="p-6 max-w-6xl mx-auto w-full space-y-6">
        {/* STAGE 1: Target Selection */}
        <section className="p-5 rounded-2xl bg-[#0E1A1D]/80 border border-[#1B292D] shadow-md space-y-4">
          <div className="flex items-center gap-3">
            <span className="w-6 h-6 rounded-full bg-[#4EBEA4] text-[#0A1214] font-bold text-xs flex items-center justify-center font-mono">
              1
            </span>
            <div>
              <h2 className="text-sm font-bold text-[#F2F7FF]">
                Select Target
              </h2>
              <p className="text-xs text-[#859CA6]">
                The telomerase macromolecular subunit to screen inhibitors against.
              </p>
            </div>
          </div>

          <div className="pl-9 space-y-4">
            <div className="p-3.5 rounded-xl bg-[#0A1214] border border-[#4EBEA4]/40 flex items-start gap-3 max-w-xl">
              <span className="w-2.5 h-2.5 rounded-full bg-[#4EBEA4] mt-1.5 flex-shrink-0" />
              <div className="space-y-1">
                <div className="flex items-center gap-2">
                  <h3 className="font-bold text-sm text-[#F2F7FF]">
                    hTERT (human Telomerase Reverse Transcriptase)
                  </h3>
                  <span className="text-[10px] font-mono px-2 py-0.5 rounded bg-[#152328] text-[#4EBEA4]">
                    Active Target
                  </span>
                </div>
                <p className="text-xs text-[#91A6BE] leading-relaxed">
                  Catalytic core reverse transcriptase polypeptide (Chain A in PDB 9Q14) complexed with small-molecule inhibitor BIBR1532.
                </p>
                <div className="text-[11px] font-mono text-[#5E7594] pt-1 flex items-center gap-3">
                  <span>ChEMBL: 5342</span>
                  <span>•</span>
                  <span className="text-emerald-400 flex items-center gap-1">
                    <CheckCircle2 className="w-3 h-3" />
                    Trained QSAR Model Ready
                  </span>
                </div>
              </div>
            </div>

            {/* Run Controls Row */}
            <div className="flex flex-wrap items-center gap-3 pt-1">
              <label htmlFor="shortlist-count" className="text-xs font-mono text-[#91A6BE]">
                Shortlist Size:
              </label>
              <input
                id="shortlist-count"
                type="number"
                min={1}
                max={12}
                value={shortlistCount}
                onChange={(e) => setShortlistCount(Math.max(1, Math.min(12, parseInt(e.target.value) || 6)))}
                className="w-16 px-2.5 py-1.5 rounded-lg bg-[#0C1423] border border-[#1e3250] text-xs font-mono text-[#F2F7FF] outline-none focus:border-[#63E6DE]"
              />

              <button
                onClick={handleRun}
                disabled={isLoadingScreening}
                className="px-4 py-2 rounded-lg bg-[#438DFF] hover:bg-[#347ce6] disabled:opacity-50 text-white font-mono text-xs font-bold transition flex items-center gap-2 shadow-md"
              >
                {isLoadingScreening ? (
                  <>
                    <Clock className="w-3.5 h-3.5 animate-spin text-[#63E6DE]" />
                    <span>Scoring Candidates…</span>
                  </>
                ) : (
                  <>
                    <Play className="w-3.5 h-3.5" />
                    <span>Run QSAR Screening</span>
                  </>
                )}
              </button>

              <span className="text-xs font-mono text-[#91A6BE]">
                {candidates.length} molecules screened • top {shortlistCount} shortlisted
              </span>
            </div>
          </div>
        </section>

        {/* STAGE 2: Candidate Molecules Screened */}
        <section className="p-5 rounded-2xl bg-[#152237] border border-[#1e3250] shadow-md space-y-4">
          <div className="flex items-center gap-3">
            <span className="w-6 h-6 rounded-full bg-[#A79BEE] text-[#0C1423] font-bold text-xs flex items-center justify-center font-mono">
              2
            </span>
            <div>
              <h2 className="text-sm font-bold text-[#F2F7FF]">
                Candidate Molecules Screened
              </h2>
              <p className="text-xs text-[#91A6BE]">
                {candidates.length} candidate molecules screened against human telomerase.
              </p>
            </div>
          </div>

          <div className="pl-9 space-y-2.5">
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-2.5">
              {candidates.slice(0, shortlistCount).map((c) => (
                <div
                  key={c.id}
                  onClick={() => onSelectCandidate(c.id)}
                  className={`p-3 rounded-xl border transition cursor-pointer ${
                    selectedCandidateId === c.id
                      ? 'bg-[#1c2e4a] border-[#63E6DE] glow-cyan'
                      : 'bg-[#0C1423]/70 border-[#1e3250] hover:border-[#1c2e4a]'
                  }`}
                >
                  <div className="flex items-center justify-between">
                    <span className="font-bold text-xs text-[#F2F7FF] flex items-center gap-1.5">
                      <span className="w-4 h-4 rounded-full bg-[#152237] text-[10px] font-mono text-[#63E6DE] flex items-center justify-center border border-[#1e3250]">
                        #{c.rank || 1}
                      </span>
                      {c.name}
                    </span>
                    {c.prediction?.pubchem_cid && (
                      <a
                        href={`https://pubchem.ncbi.nlm.nih.gov/compound/${c.prediction.pubchem_cid}`}
                        target="_blank"
                        rel="noreferrer"
                        onClick={(e) => e.stopPropagation()}
                        className="text-[10px] font-mono px-1.5 py-0.5 rounded bg-[#152237] text-[#91A6BE] hover:text-[#438DFF] border border-[#1e3250]"
                      >
                        CID {c.prediction.pubchem_cid}
                      </a>
                    )}
                  </div>
                  <p className="text-[11px] text-[#91A6BE] line-clamp-2 mt-1 leading-snug">
                    {c.note}
                  </p>
                </div>
              ))}
            </div>
          </div>
        </section>

        {/* STAGE 3: Ranked Results & Potency Plot */}
        <section className="p-5 rounded-2xl bg-[#152237] border border-[#1e3250] shadow-md space-y-5">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-3">
              <span className="w-6 h-6 rounded-full bg-[#FF7D45] text-[#0C1423] font-bold text-xs flex items-center justify-center font-mono">
                3
              </span>
              <div>
                <h2 className="text-sm font-bold text-[#F2F7FF]">
                  Results &amp; Ranked Potency Plot
                </h2>
                <p className="text-xs text-[#91A6BE]">
                  Machine learning QSAR pIC50 score for each molecule (higher = more potent).
                </p>
              </div>
            </div>

            <button
              onClick={() => setShowTableView(!showTableView)}
              className="px-3 py-1 text-xs font-mono rounded-lg bg-[#0C1423] text-[#91A6BE] hover:text-[#F2F7FF] border border-[#1e3250] transition flex items-center gap-1"
            >
              {showTableView ? 'Hide Table View' : 'Show Table View'}
              {showTableView ? <ChevronUp className="w-3 h-3" /> : <ChevronDown className="w-3 h-3" />}
            </button>
          </div>

          <div className="pl-9 space-y-5">
            {/* Legend */}
            <div className="flex flex-wrap items-center gap-4 text-xs font-mono text-[#91A6BE] pb-2 border-b border-[#1c2e4a]">
              <div className="flex items-center gap-1.5">
                <span className="w-2.5 h-2.5 rounded-full bg-[#438DFF]" />
                <span className="text-[#F2F7FF]">Predicted pIC50 (Model)</span>
              </div>
              <div className="flex items-center gap-1.5">
                <span className="w-2.5 h-2.5 rounded-full bg-[#FF7D45]" />
                <span className="text-[#F2F7FF]">Measured pIC50 (ChEMBL Experimental)</span>
              </div>
              <div className="text-[11px] text-[#5E7594]">
                Numbered rows are the top shortlisted candidates
              </div>
            </div>

            {/* Interactive Dot Plot */}
            <div className="space-y-2 relative">
              {scoredCandidates.slice(0, shortlistCount).map((c) => {
                const isSelected = selectedCandidateId === c.id;
                const p = c.prediction!;
                return (
                  <div
                    key={c.id}
                    onClick={() => onSelectCandidate(c.id)}
                    className={`grid grid-cols-12 items-center gap-2 py-1.5 px-2 rounded-lg cursor-pointer transition ${
                      isSelected ? 'bg-[#1c2e4a] text-[#F2F7FF]' : 'hover:bg-[#121c2e] text-[#91A6BE]'
                    }`}
                  >
                    {/* Rank */}
                    <div className="col-span-1 text-xs font-mono font-bold flex items-center">
                      <span
                        className={`w-5 h-5 rounded-full flex items-center justify-center text-[10px] ${
                          isSelected ? 'bg-[#63E6DE] text-[#0C1423]' : 'bg-[#0C1423] text-[#91A6BE]'
                        }`}
                      >
                        {c.rank || 1}
                      </span>
                    </div>

                    {/* Compound Name */}
                    <div className="col-span-3 text-xs font-semibold truncate" title={c.name}>
                      {c.name}
                    </div>

                    {/* Dot Track */}
                    <div className="col-span-6 relative h-6 bg-[#0C1423] rounded-md border border-[#1e3250] overflow-hidden">
                      {/* Grid vertical lines */}
                      {AXIS.ticks.map((t) => (
                        <div
                          key={t}
                          className="absolute top-0 bottom-0 w-px bg-[#1c2e4a]"
                          style={{ left: `${pos(t)}%` }}
                        />
                      ))}

                      {/* Measured dot (if available) */}
                      {p.measured_pic50 != null && (
                        <button
                          type="button"
                          onMouseEnter={(e) => {
                            const rect = e.currentTarget.getBoundingClientRect();
                            setHoveredPoint({ candidate: c, type: 'meas', x: rect.left, y: rect.top });
                          }}
                          onMouseLeave={() => setHoveredPoint(null)}
                          className="absolute top-1/2 -translate-y-1/2 -translate-x-1/2 w-4 h-4 rounded-full flex items-center justify-center z-10 transition hover:scale-125"
                          style={{ left: `${pos(p.measured_pic50)}%` }}
                        >
                          <span className="w-2.5 h-2.5 rounded-full bg-[#FF7D45] shadow-sm" />
                        </button>
                      )}

                      {/* Predicted dot */}
                      <button
                        type="button"
                        onMouseEnter={(e) => {
                          const rect = e.currentTarget.getBoundingClientRect();
                          setHoveredPoint({ candidate: c, type: 'pred', x: rect.left, y: rect.top });
                        }}
                        onMouseLeave={() => setHoveredPoint(null)}
                        className="absolute top-1/2 -translate-y-1/2 -translate-x-1/2 w-4 h-4 rounded-full flex items-center justify-center z-10 transition hover:scale-125"
                        style={{ left: `${pos(p.predicted_pic50)}%` }}
                      >
                        <span className="w-2.5 h-2.5 rounded-full bg-[#438DFF] shadow-sm ring-1 ring-[#63E6DE]" />
                      </button>
                    </div>

                    {/* Predicted pIC50 */}
                    <div className="col-span-1 text-right text-xs font-mono font-bold text-[#438DFF]">
                      {p.predicted_pic50.toFixed(2)}
                    </div>

                    {/* IC50 nM */}
                    <div className="col-span-1 text-right text-[11px] font-mono text-[#91A6BE]">
                      {Math.round(p.predicted_ic50_nm)} nM
                    </div>
                  </div>
                );
              })}

              {/* Axis Ticks */}
              <div className="grid grid-cols-12 gap-2 pt-1 border-t border-[#1c2e4a] text-[10px] font-mono text-[#5E7594]">
                <div className="col-span-4 text-left">Axis Scale:</div>
                <div className="col-span-6 relative h-4">
                  {AXIS.ticks.map((t) => (
                    <div
                      key={t}
                      className="absolute -translate-x-1/2"
                      style={{ left: `${pos(t)}%` }}
                    >
                      {t}
                    </div>
                  ))}
                </div>
                <div className="col-span-2 text-right">predicted pIC50</div>
              </div>
            </div>

            {/* Hover Tooltip Popup */}
            {hoveredPoint && (
              <div
                className="fixed z-50 p-3 rounded-xl bg-[#152237] border border-[#63E6DE]/50 shadow-2xl text-xs font-mono space-y-1 pointer-events-none"
                style={{
                  left: `${hoveredPoint.x + 10}px`,
                  top: `${hoveredPoint.y - 60}px`
                }}
              >
                <div className="font-bold text-[#F2F7FF]">
                  {hoveredPoint.candidate.name}
                </div>
                <div className="text-[#91A6BE]">
                  {hoveredPoint.type === 'pred' ? (
                    <>
                      <span className="text-[#438DFF] font-semibold">Predicted pIC50:</span>{' '}
                      {hoveredPoint.candidate.prediction?.predicted_pic50.toFixed(2)} (
                      {Math.round(hoveredPoint.candidate.prediction?.predicted_ic50_nm || 0)} nM)
                    </>
                  ) : (
                    <>
                      <span className="text-[#FF7D45] font-semibold">ChEMBL Measured:</span>{' '}
                      {hoveredPoint.candidate.prediction?.measured_pic50?.toFixed(2)}
                    </>
                  )}
                </div>
                <div className="text-[10px] text-[#5E7594]">
                  Tanimoto to training set: {hoveredPoint.candidate.prediction?.max_tanimoto.toFixed(2)}
                </div>
              </div>
            )}

            {/* Detailed Cards Grid */}
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4 pt-4 border-t border-[#1c2e4a]">
              {scoredCandidates.slice(0, shortlistCount).map((c) => {
                const p = c.prediction!;
                const pr = c.profile || {};
                const isSelected = selectedCandidateId === c.id;

                return (
                  <div
                    key={c.id}
                    className={`p-4 rounded-2xl border transition space-y-3 ${
                      isSelected
                        ? 'bg-[#1c2e4a] border-[#63E6DE] shadow-lg'
                        : 'bg-[#0C1423]/80 border-[#1e3250] hover:border-[#1c2e4a]'
                    }`}
                  >
                    <div className="flex items-start gap-3">
                      {/* PubChem 2D Structure Image */}
                      {p.pubchem_cid ? (
                        <img
                          src={`https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/cid/${p.pubchem_cid}/PNG?image_size=160x160`}
                          alt={`2D Structure of ${c.name}`}
                          className="w-16 h-16 rounded-lg bg-white p-1 border border-[#1e3250] object-contain flex-shrink-0"
                          loading="lazy"
                        />
                      ) : (
                        <div className="w-16 h-16 rounded-lg bg-[#152237] border border-[#1e3250] flex items-center justify-center text-xs font-mono text-[#5E7594]">
                          2D
                        </div>
                      )}

                      <div className="flex-1 min-w-0">
                        <div className="flex items-center justify-between">
                          <h3 className="font-bold text-sm text-[#F2F7FF] truncate">
                            {c.name}
                          </h3>
                          <span className="text-[10px] font-mono px-2 py-0.5 rounded-full bg-[#0C1423] text-[#63E6DE] font-semibold">
                            Rank #{c.rank || 1}
                          </span>
                        </div>
                        <div className="text-xs font-mono text-[#438DFF] font-semibold mt-0.5">
                          Pred. pIC50 {p.predicted_pic50.toFixed(2)} • {Math.round(p.predicted_ic50_nm)} nM
                        </div>
                        {p.measured_pic50 != null && (
                          <div className="text-[11px] font-mono text-[#FF7D45]">
                            ChEMBL Measured: {p.measured_pic50.toFixed(2)} ({p.measured_count || 1} assay{p.measured_count && p.measured_count > 1 ? 's' : ''})
                          </div>
                        )}
                      </div>
                    </div>

                    {/* Badges */}
                    <div className="flex flex-wrap gap-1.5 text-[10px] font-mono">
                      <span
                        className={`px-2 py-0.5 rounded border ${
                          p.domain === 'in'
                            ? 'bg-emerald-950/60 text-emerald-400 border-emerald-800/40'
                            : 'bg-amber-950/60 text-amber-400 border-amber-800/40'
                        }`}
                      >
                        {p.domain === 'in' ? 'Inside Domain' : 'Outside Domain'}
                      </span>
                      {pr.lipinski_pass !== undefined && (
                        <span
                          className={`px-2 py-0.5 rounded border ${
                            pr.lipinski_pass
                              ? 'bg-emerald-950/60 text-emerald-400 border-emerald-800/40'
                              : 'bg-red-950/60 text-red-400 border-red-800/40'
                          }`}
                        >
                          Lipinski Violations: {pr.lipinski_violations || 0}
                        </span>
                      )}
                      {pr.veber_pass !== undefined && (
                        <span
                          className={`px-2 py-0.5 rounded border ${
                            pr.veber_pass
                              ? 'bg-emerald-950/60 text-emerald-400 border-emerald-800/40'
                              : 'bg-amber-950/60 text-amber-400 border-amber-800/40'
                          }`}
                        >
                          {pr.veber_pass ? 'Veber Pass' : 'Veber Fail'}
                        </span>
                      )}
                    </div>

                    {/* Similarity & QED Meters */}
                    <div className="space-y-1.5 text-[10px] font-mono">
                      <div>
                        <div className="flex justify-between text-[#91A6BE]">
                          <span>Similarity to training set (Tanimoto):</span>
                          <span className="text-[#F2F7FF] font-bold">{p.max_tanimoto.toFixed(2)}</span>
                        </div>
                        <div className="w-full h-1.5 bg-[#0C1423] rounded-full overflow-hidden mt-0.5">
                          <div
                            className={`h-full ${p.max_tanimoto >= 0.5 ? 'bg-emerald-500' : 'bg-amber-500'}`}
                            style={{ width: `${Math.min(100, p.max_tanimoto * 100)}%` }}
                          />
                        </div>
                      </div>

                      {pr.qed !== undefined && (
                        <div>
                          <div className="flex justify-between text-[#91A6BE]">
                            <span>Drug-likeness (QED):</span>
                            <span className="text-[#F2F7FF] font-bold">{pr.qed.toFixed(3)}</span>
                          </div>
                          <div className="w-full h-1.5 bg-[#0C1423] rounded-full overflow-hidden mt-0.5">
                            <div
                              className="h-full bg-[#438DFF]"
                              style={{ width: `${Math.min(100, pr.qed * 100)}%` }}
                            />
                          </div>
                        </div>
                      )}
                    </div>

                    {/* Action: Explore in 3D */}
                    <div className="pt-2 border-t border-[#1c2e4a] flex items-center justify-between">
                      <span className="text-[10px] font-mono text-[#5E7594]">
                        MW: {pr.molecular_weight || c.molecularWeight} g/mol
                      </span>
                      <button
                        onClick={() => {
                          onSelectCandidate(c.id);
                          onExploreInPlayground(c.id);
                        }}
                        className="px-3 py-1 rounded-lg bg-[#1c2e4a] hover:bg-[#253d63] text-[#63E6DE] text-xs font-mono font-medium border border-[#63E6DE]/30 transition flex items-center gap-1.5"
                      >
                        <span>Explore in 3D Viewer</span>
                        <ArrowRight className="w-3 h-3" />
                      </button>
                    </div>
                  </div>
                );
              })}
            </div>

            {/* Optional Tabular View */}
            {showTableView && (
              <div className="p-4 rounded-2xl bg-[#0C1423] border border-[#1e3250] overflow-x-auto space-y-2">
                <div className="text-xs font-mono font-bold text-[#F2F7FF]">
                  Complete QSAR &amp; Property Matrix:
                </div>
                <table className="w-full text-left text-xs font-mono border-collapse">
                  <thead>
                    <tr className="border-b border-[#1c2e4a] text-[#5E7594] text-[10px] uppercase">
                      <th className="py-2 px-2">#</th>
                      <th className="py-2 px-2">Compound</th>
                      <th className="py-2 px-2">Pred pIC50</th>
                      <th className="py-2 px-2">IC50 (nM)</th>
                      <th className="py-2 px-2">ChEMBL Meas</th>
                      <th className="py-2 px-2">Tanimoto</th>
                      <th className="py-2 px-2">Domain</th>
                      <th className="py-2 px-2">QED</th>
                      <th className="py-2 px-2">Lipinski</th>
                      <th className="py-2 px-2">Action</th>
                    </tr>
                  </thead>
                  <tbody>
                    {scoredCandidates.slice(0, shortlistCount).map((c) => {
                      const p = c.prediction!;
                      const pr = c.profile || {};
                      return (
                        <tr key={c.id} className="border-b border-[#1e3250]/60 hover:bg-[#152237]">
                          <td className="py-2 px-2 font-bold text-[#63E6DE]">#{c.rank || 1}</td>
                          <td className="py-2 px-2 text-[#F2F7FF] font-semibold">{c.name}</td>
                          <td className="py-2 px-2 text-[#438DFF]">{p.predicted_pic50.toFixed(2)}</td>
                          <td className="py-2 px-2 text-[#91A6BE]">{Math.round(p.predicted_ic50_nm)} nM</td>
                          <td className="py-2 px-2 text-[#FF7D45]">
                            {p.measured_pic50 != null ? p.measured_pic50.toFixed(2) : '—'}
                          </td>
                          <td className="py-2 px-2">{p.max_tanimoto.toFixed(2)}</td>
                          <td className="py-2 px-2">
                            <span className={p.domain === 'in' ? 'text-emerald-400' : 'text-amber-400'}>
                              {p.domain}
                            </span>
                          </td>
                          <td className="py-2 px-2">{pr.qed?.toFixed(3) || '—'}</td>
                          <td className="py-2 px-2">{pr.lipinski_violations ?? 0} viol.</td>
                          <td className="py-2 px-2">
                            <button
                              onClick={() => {
                                onSelectCandidate(c.id);
                                onExploreInPlayground(c.id);
                              }}
                              className="text-[#63E6DE] hover:underline"
                            >
                              Explore in 3D
                            </button>
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        </section>
      </div>
    </div>
  );
};
