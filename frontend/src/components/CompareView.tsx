/**
 * @license
 * SPDX-License-Identifier: Apache-2.0
 */

import React, { useState } from 'react';
import {
  GitCompare,
  FlaskConical,
  Clock,
  AlertTriangle,
  FileText,
  PlusCircle,
  Shield,
  Flame,
  CheckCircle2,
  ExternalLink,
  ArrowRight,
  Info,
  Layers,
  Sparkles,
  Atom
} from 'lucide-react';
import { Ligand, DockingResult, ResearchNote, Protein } from '../types/docking';
import {
  Candidate,
  potencyEvidence,
  structuralEvidence,
  dockingEvidence,
  badgesFor,
  metersFor,
  depictionUrl,
  propertyLine,
  DOMAIN_THRESHOLD
} from '../dockshiftApi';

interface CompareViewProps {
  protein: Protein;
  candidates: Ligand[];
  dockingResults: Record<string, DockingResult>;
  notes: ResearchNote[];
  onAddNoteForCandidate: (candidateId: string) => void;
  onNavigateToTab: (tab: any) => void;
  onExploreInPlayground?: (candidateId: string) => void;
}

const toCandidateAdapter = (l: Ligand): Candidate => ({
  rank: l.rank || 1,
  name: l.name,
  shortlisted: !!l.selected,
  note: l.note || l.description,
  smiles: l.smiles || l.prediction?.smiles,
  pubchemCid: l.prediction?.pubchem_cid,
  prediction: (l.prediction as any) || {},
  profile: (l.profile as any) || {}
});

export const CompareView: React.FC<CompareViewProps> = ({
  protein,
  candidates,
  dockingResults,
  notes,
  onAddNoteForCandidate,
  onNavigateToTab,
  onExploreInPlayground
}) => {
  const [selectedIdA, setSelectedIdA] = useState<string>(candidates[0]?.id || 'bibr1532');
  const [selectedIdB, setSelectedIdB] = useState<string>(candidates[1]?.id || 'mst-312');

  const candidateA = candidates.find((c) => c.id === selectedIdA) || candidates[0];
  const candidateB = candidates.find((c) => c.id === selectedIdB) || candidates[1] || candidates[0];

  const candA = toCandidateAdapter(candidateA);
  const candB = toCandidateAdapter(candidateB);

  const potEvA = potencyEvidence(candA);
  const potEvB = potencyEvidence(candB);
  const structEvA = structuralEvidence(candA);
  const structEvB = structuralEvidence(candB);
  const dockEvA = dockingEvidence(candA);
  const dockEvB = dockingEvidence(candB);

  const badgesA = badgesFor(candA);
  const badgesB = badgesFor(candB);
  const metersA = metersFor(candA);
  const metersB = metersFor(candB);

  const notesA = notes.filter((n) => n.candidateId === candidateA?.id);
  const notesB = notes.filter((n) => n.candidateId === candidateB?.id);

  const renderCandidateCard = (
    c: Ligand,
    adapterCand: Candidate,
    potEv: ReturnType<typeof potencyEvidence>,
    structEv: ReturnType<typeof structuralEvidence>,
    dockEv: ReturnType<typeof dockingEvidence>,
    badges: ReturnType<typeof badgesFor>,
    meters: ReturnType<typeof metersFor>,
    notesCount: number
  ) => {
    const imgUrl = depictionUrl(adapterCand);
    const propSummary = propertyLine(adapterCand);

    return (
      <div className="p-5 rounded-2xl bg-[#152237] border border-[#1e3250] shadow-xl space-y-4 flex flex-col justify-between">
        <div className="space-y-4">
          {/* Header row with 2D PubChem Depiction */}
          <div className="flex items-start gap-3 pb-3 border-b border-[#1c2e4a]">
            {imgUrl ? (
              <img
                src={imgUrl}
                alt={c.name}
                className="w-20 h-20 rounded-xl bg-white p-1 border border-[#1e3250] object-contain flex-shrink-0 shadow-sm"
                loading="lazy"
              />
            ) : (
              <div className="w-20 h-20 rounded-xl bg-[#0C1423] border border-[#1e3250] flex flex-col items-center justify-center text-xs font-mono text-[#5E7594] flex-shrink-0">
                <Atom className="w-6 h-6 mb-1 text-[#5E7594]" />
                <span>2D N/A</span>
              </div>
            )}

            <div className="flex-1 min-w-0">
              <div className="flex items-center justify-between">
                <h2 className="text-base font-bold text-[#F2F7FF] truncate">
                  {c.name}
                </h2>
                <span className="text-[10px] font-mono px-2 py-0.5 rounded bg-[#0C1423] text-[#63E6DE] border border-[#1e3250]">
                  #{c.rank || 1}
                </span>
              </div>
              <span className="text-[11px] font-mono text-[#438DFF] block mt-0.5">
                {c.tag || 'Shortlisted Candidate'}
              </span>
              <div className="text-[10px] text-[#91A6BE] mt-1 line-clamp-2">
                {c.note || c.description}
              </div>
            </div>
          </div>

          {/* Badges row */}
          {badges.length > 0 && (
            <div className="flex flex-wrap gap-1.5">
              {badges.map((b, idx) => (
                <span
                  key={idx}
                  title={b.title}
                  className={`px-2 py-0.5 rounded text-[10px] font-mono font-medium ${
                    b.tone === 'good'
                      ? 'bg-emerald-950/60 text-emerald-400 border border-emerald-800/40'
                      : b.tone === 'warn'
                      ? 'bg-amber-950/60 text-amber-300 border border-amber-800/40'
                      : 'bg-[#0C1423] text-[#63E6DE] border border-[#1e3250]'
                  }`}
                >
                  {b.label}
                </span>
              ))}
            </div>
          )}

          {/* Four Evidence Classes (Requirement 5 from Integration Plan) */}
          <div className="space-y-2 pt-1">
            <div className="text-[10px] font-mono uppercase tracking-wider text-[#91A6BE] flex items-center gap-1.5">
              <Shield className="w-3 h-3 text-[#438DFF]" />
              Four Evidence Classes (Strict Separation)
            </div>

            {/* 1. QSAR Predicted */}
            {potEv.filter((e) => e.kind === 'qsar_predicted').map((e, i) => (
              <div key={i} className="p-3 rounded-xl bg-[#0C1423] border border-[#438DFF]/30 space-y-1">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-1.5">
                    <span className="w-2 h-2 rounded-full bg-[#438DFF]" />
                    <span className="text-[11px] font-mono font-semibold text-[#438DFF]">
                      1. QSAR Predicted Potency
                    </span>
                  </div>
                  <span className="text-base font-mono font-bold text-[#438DFF]">
                    pIC50 {e.pic50.toFixed(2)}
                  </span>
                </div>
                {e.ic50nM && (
                  <div className="text-[10px] font-mono text-[#91A6BE]">
                    Approx. IC50: <span className="text-[#F2F7FF] font-semibold">~{Math.round(e.ic50nM)} nM</span>
                  </div>
                )}
                <div className="space-y-0.5 pt-1">
                  {e.caveats.map((cav, cIdx) => (
                    <div key={cIdx} className="text-[9px] text-[#91A6BE] flex items-start gap-1">
                      <span className="text-amber-400 font-bold">•</span>
                      <span>{cav}</span>
                    </div>
                  ))}
                </div>
              </div>
            ))}

            {/* 2. ChEMBL Measured */}
            {c.prediction?.measured_pic50 != null ? (
              <div className="p-3 rounded-xl bg-[#0C1423] border border-[#FF7D45]/30 space-y-1">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-1.5">
                    <span className="w-2 h-2 rounded-full bg-[#FF7D45]" />
                    <span className="text-[11px] font-mono font-semibold text-[#FF7D45]">
                      2. ChEMBL Measured Potency
                    </span>
                  </div>
                  <span className="text-base font-mono font-bold text-[#FF7D45]">
                    pIC50 {c.prediction.measured_pic50.toFixed(2)}
                  </span>
                </div>
                <div className="text-[9px] font-mono text-[#91A6BE]">
                  Experimental wet-lab measurement ({c.prediction.measured_count || 1} trial records)
                </div>
              </div>
            ) : (
              <div className="p-2 rounded-xl bg-[#0C1423]/40 border border-[#1e3250] text-[10px] font-mono text-[#5E7594] flex items-center justify-between">
                <span>2. ChEMBL Measured:</span>
                <span className="italic">Awaiting wet-lab assay</span>
              </div>
            )}

            {/* 3. Experimental Structure */}
            {structEv ? (
              <div className="p-3 rounded-xl bg-[#0C1423] border border-[#63E6DE]/40 space-y-1">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-1.5">
                    <Flame className="w-3.5 h-3.5 text-[#FF7D45]" />
                    <span className="text-[11px] font-mono font-semibold text-[#63E6DE]">
                      3. Experimental Structure (Observed)
                    </span>
                  </div>
                  <span className="text-xs font-mono font-bold text-[#63E6DE]">
                    PDB {structEv.pdbId} ({structEv.resolutionA} Å)
                  </span>
                </div>
                <div className="text-[10px] font-mono text-[#91A6BE]">
                  Ligand <span className="text-[#FF7D45] font-semibold">{structEv.ligandCompId}</span> ({structEv.ligandName}) experimentally solved in human telomerase holoenzyme.
                </div>
                {structEv.sideChainCaveat && (
                  <div className="text-[9px] text-[#5E7594] italic pt-0.5">
                    Note: {structEv.sideChainCaveat}
                  </div>
                )}
              </div>
            ) : (
              <div className="p-2 rounded-xl bg-[#0C1423]/40 border border-[#1e3250] text-[10px] font-mono text-[#5E7594] flex items-center justify-between">
                <span>3. Experimental 3D Structure:</span>
                <span className="italic">None solved (No crystal/Cryo-EM)</span>
              </div>
            )}

            {/* 4. Docking Predicted */}
            <div className="p-2.5 rounded-xl bg-[#0C1423]/60 border border-[#1e3250] space-y-1">
              <div className="flex items-center justify-between">
                <span className="text-[11px] font-mono text-[#91A6BE] flex items-center gap-1.5">
                  <Clock className="w-3 h-3 text-[#5E7594]" />
                  4. Docking Predicted Pose
                </span>
                <span className="text-[10px] font-mono px-1.5 py-0.2 rounded bg-[#152237] text-amber-400 border border-amber-800/30">
                  {dockEv.status}
                </span>
              </div>
              <div className="text-[9px] text-[#5E7594]">
                {dockEv.status === 'unavailable' ? (dockEv as any).reason : 'Docking results stream from team pipeline.'}
              </div>
            </div>
          </div>

          {/* Model Meters */}
          {meters.length > 0 && (
            <div className="space-y-2 pt-1 border-t border-[#1c2e4a]">
              {meters.map((m, mIdx) => (
                <div key={mIdx} className="space-y-1">
                  <div className="flex justify-between text-[10px] font-mono text-[#91A6BE]">
                    <span>{m.label}:</span>
                    <span className="font-bold text-[#F2F7FF]">{m.value?.toFixed(2) ?? '—'}</span>
                  </div>
                  <div className="w-full h-1.5 rounded-full bg-[#0C1423] relative overflow-hidden">
                    <div
                      className="h-full bg-gradient-to-r from-[#438DFF] to-[#63E6DE] rounded-full transition-all"
                      style={{ width: `${Math.min(100, Math.max(0, ((m.value || 0) / m.max) * 100))}%` }}
                    />
                    {m.mark != null && (
                      <div
                        className="absolute top-0 bottom-0 w-0.5 bg-amber-400 shadow-sm"
                        style={{ left: `${(m.mark / m.max) * 100}%` }}
                        title={`Domain threshold: ${m.mark}`}
                      />
                    )}
                  </div>
                  {m.caption && (
                    <div className="text-[9px] font-mono text-[#5E7594]">{m.caption}</div>
                  )}
                </div>
              ))}
            </div>
          )}

          {/* Physicochemical Properties Line */}
          {propSummary && (
            <div className="p-2 rounded-lg bg-[#0C1423] border border-[#1e3250] text-[10px] font-mono text-[#91A6BE] leading-relaxed">
              {propSummary}
            </div>
          )}

          {/* SMILES */}
          {c.smiles && (
            <div className="p-2 rounded bg-[#0C1423] border border-[#1e3250] text-[9px] font-mono">
              <span className="text-[#5E7594] block mb-0.5">SMILES</span>
              <span className="text-[#91A6BE] break-all">{c.smiles}</span>
            </div>
          )}
        </div>

        {/* Card Footer Actions */}
        <div className="pt-3 border-t border-[#1c2e4a] flex items-center gap-2">
          <button
            onClick={() => onExploreInPlayground && onExploreInPlayground(c.id)}
            className="flex-1 py-2 px-3 rounded-xl bg-[#1c2e4a] hover:bg-[#253d63] text-[#63E6DE] font-mono text-xs font-semibold border border-[#63E6DE]/30 transition flex items-center justify-center gap-1.5"
          >
            <span>Explore in 3D Viewer</span>
            <ArrowRight className="w-3.5 h-3.5" />
          </button>
          <button
            onClick={() => onAddNoteForCandidate(c.id)}
            title="Log Lab Observation"
            className="p-2 rounded-xl bg-[#0C1423] hover:bg-[#152237] border border-[#1e3250] text-[#91A6BE] hover:text-[#63E6DE] transition"
          >
            <FileText className="w-4 h-4" />
          </button>
        </div>
      </div>
    );
  };

  return (
    <div className="h-full flex flex-col bg-[#0C1423] text-[#F2F7FF] overflow-y-auto select-none">
      {/* View Header */}
      <div className="px-6 py-4 border-b border-[#1c2e4a] bg-[#0E1728]/90 flex flex-wrap items-center justify-between gap-4">
        <div>
          <div className="flex items-center gap-2">
            <GitCompare className="w-5 h-5 text-[#438DFF]" />
            <h1 className="text-lg font-bold tracking-tight text-[#F2F7FF]">
              Candidate Comparison &amp; Benchmark Analysis
            </h1>
            <span className="px-2 py-0.5 text-xs font-mono rounded bg-[#1c2e4a] text-[#438DFF] border border-[#438DFF]/20">
              QSAR vs. ChEMBL Measured
            </span>
          </div>
          <p className="text-xs text-[#91A6BE] mt-0.5">
            Compare candidate molecules side-by-side using real QSAR predictions, ChEMBL measured values, and the 4 scientific evidence classes.
          </p>
        </div>

        <div className="flex items-center gap-2.5">
          <button
            onClick={() => onNavigateToTab('literature')}
            className="px-3 py-1.5 text-xs font-mono rounded-lg bg-[#152237] hover:bg-[#1c2e4a] text-[#F2F7FF] border border-[#1e3250] transition flex items-center gap-1.5"
          >
            <ExternalLink className="w-3.5 h-3.5 text-[#438DFF]" />
            Literature Evidence
          </button>
        </div>
      </div>

      <div className="p-6 max-w-7xl mx-auto w-full space-y-6">
        {/* Selector Bar */}
        <div className="grid grid-cols-1 md:grid-cols-2 gap-6 bg-[#152237] p-4 rounded-2xl border border-[#1e3250]">
          <div>
            <label className="text-xs font-mono text-[#91A6BE] block mb-1">
              Select Primary Compound (Slot A):
            </label>
            <select
              value={selectedIdA}
              onChange={(e) => setSelectedIdA(e.target.value)}
              className="w-full px-3 py-2 bg-[#0C1423] border border-[#1e3250] rounded-xl text-xs font-mono text-[#F2F7FF] outline-none focus:border-[#438DFF]"
            >
              {candidates.map((c) => (
                <option key={c.id} value={c.id}>
                  #{c.rank || 1} {c.name} ({c.prediction ? `Pred. pIC50 ${c.prediction.predicted_pic50.toFixed(2)}` : ''})
                </option>
              ))}
            </select>
          </div>

          <div>
            <label className="text-xs font-mono text-[#91A6BE] block mb-1">
              Select Comparison Compound (Slot B):
            </label>
            <select
              value={selectedIdB}
              onChange={(e) => setSelectedIdB(e.target.value)}
              className="w-full px-3 py-2 bg-[#0C1423] border border-[#1e3250] rounded-xl text-xs font-mono text-[#F2F7FF] outline-none focus:border-[#438DFF]"
            >
              {candidates.map((c) => (
                <option key={c.id} value={c.id}>
                  #{c.rank || 1} {c.name} ({c.prediction ? `Pred. pIC50 ${c.prediction.predicted_pic50.toFixed(2)}` : ''})
                </option>
              ))}
            </select>
          </div>
        </div>

        {/* Side-by-Side Comparison Cards */}
        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
          {renderCandidateCard(
            candidateA,
            candA,
            potEvA,
            structEvA,
            dockEvA,
            badgesA,
            metersA,
            notesA.length
          )}
          {renderCandidateCard(
            candidateB,
            candB,
            potEvB,
            structEvB,
            dockEvB,
            badgesB,
            metersB,
            notesB.length
          )}
        </div>
      </div>
    </div>
  );
};
