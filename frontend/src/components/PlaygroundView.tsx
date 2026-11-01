/**
 * @license
 * SPDX-License-Identifier: Apache-2.0
 */

import React, { useState } from 'react';
import {
  Sliders,
  Sparkles,
  Dna,
  Shield,
  Crosshair,
  ArrowRight,
  Clock,
  Play,
  RotateCcw,
  CheckCircle2,
  AlertCircle,
  FilePlus,
  Flame,
  Layers,
  Activity
} from 'lucide-react';
import { Protein, Ligand, DockingResult, SelectedComponentType } from '../types/docking';

interface PlaygroundViewProps {
  protein: Protein;
  candidates: Ligand[];
  selectedCandidateId: string;
  onSelectCandidate: (id: string) => void;
  dockingResults: Record<string, DockingResult>;
  onSelectComponent: (component: SelectedComponentType) => void;
  onFocusResidue: (residue: { resi: number; chain: string }) => void;
  onFocusInhibitor: () => void;
  onNavigateToTab: (tab: any) => void;
  onAddNote: (category: 'Observation' | 'Question' | 'Hypothesis' | 'Next Experiment', content: string) => void;
}

export const PlaygroundView: React.FC<PlaygroundViewProps> = ({
  protein,
  candidates,
  selectedCandidateId,
  onSelectCandidate,
  dockingResults,
  onSelectComponent,
  onFocusResidue,
  onFocusInhibitor,
  onNavigateToTab,
  onAddNote
}) => {
  const defaultCandidate: Ligand = {
    id: 'candidate-a',
    name: 'Candidate A (BIBR Analog)',
    chemicalFormula: 'C15H13NO3',
    molecularWeight: 255.27,
    description: 'Scaffold placeholder targeting the TERT thumb/palm allosteric pocket.',
    tag: 'Pipeline Candidate',
    targetSite: 'BIBR1532 Allosteric Pocket (TERT Thumb/Palm)'
  };

  const currentCandidate =
    candidates && candidates.length > 0
      ? candidates.find((c) => c.id === selectedCandidateId) || candidates[0]
      : defaultCandidate;
  const currentDocking = dockingResults[selectedCandidateId];

  // Grid box parameters for 9Q14 BIBR1532 allosteric pocket
  const [boxCenter, setBoxCenter] = useState({ x: 208.5, y: 226.3, z: 182.0 });
  const [boxSize, setBoxSize] = useState({ x: 22.0, y: 22.0, z: 24.0 });
  const [exhaustiveness, setExhaustiveness] = useState(16);
  const [scoringEngine, setScoringEngine] = useState('AutoDock Vina v1.2.5');
  const [pipelineState, setPipelineState] = useState<'idle' | 'queued' | 'simulating'>('idle');
  const [activeSubTab, setActiveSubTab] = useState<'bibr_pocket' | 'subunits' | 'grid'>('bibr_pocket');

  const handleSimulateQueue = () => {
    setPipelineState('queued');
    setTimeout(() => {
      setPipelineState('simulating');
      setTimeout(() => {
        setPipelineState('idle');
        onAddNote(
          'Observation',
          `Simulated grid box search for ${currentCandidate.name} centered at BIBR1532 allosteric pocket [${boxCenter.x}, ${boxCenter.y}, ${boxCenter.z}]. Backend job queued for MIT computational docking pipeline.`
        );
      }, 2000);
    }, 1000);
  };

  return (
    <div className="h-full flex flex-col bg-[#0C1423] text-[#F2F7FF] overflow-y-auto">
      {/* Header */}
      <div className="px-6 py-4 border-b border-[#1c2e4a] bg-[#0E1728]/80 flex flex-wrap items-center justify-between gap-4">
        <div>
          <div className="flex items-center gap-2">
            <Sliders className="w-5 h-5 text-[#63E6DE]" />
            <h1 className="text-lg font-semibold tracking-tight text-[#F2F7FF]">
              Molecular Playground
            </h1>
            <span className="px-2 py-0.5 text-xs font-mono rounded bg-[#1c2e4a] text-[#63E6DE] border border-[#63E6DE]/20">
              Telomerase (9Q14)
            </span>
          </div>
          <p className="text-xs text-[#91A6BE] mt-0.5">
            Probe the BIBR1532 allosteric pocket, inspect TERT &amp; TERC subunits, and configure computational docking grids.
          </p>
        </div>

        {/* Tab switcher */}
        <div className="flex bg-[#152237] p-1 rounded-xl border border-[#1e3250] text-xs font-mono">
          <button
            onClick={() => setActiveSubTab('bibr_pocket')}
            className={`px-3 py-1.5 rounded-lg transition ${
              activeSubTab === 'bibr_pocket'
                ? 'bg-[#1c2e4a] text-[#FF7D45] font-semibold'
                : 'text-[#91A6BE] hover:text-[#F2F7FF]'
            }`}
          >
            BIBR1532 Pocket
          </button>
          <button
            onClick={() => setActiveSubTab('subunits')}
            className={`px-3 py-1.5 rounded-lg transition ${
              activeSubTab === 'subunits'
                ? 'bg-[#1c2e4a] text-[#A79BEE] font-semibold'
                : 'text-[#91A6BE] hover:text-[#F2F7FF]'
            }`}
          >
            Complex Subunits
          </button>
          <button
            onClick={() => setActiveSubTab('grid')}
            className={`px-3 py-1.5 rounded-lg transition ${
              activeSubTab === 'grid'
                ? 'bg-[#1c2e4a] text-[#438DFF] font-semibold'
                : 'text-[#91A6BE] hover:text-[#F2F7FF]'
            }`}
          >
            Backend Docking Grid
          </button>
        </div>
      </div>

      <div className="p-6 max-w-7xl mx-auto w-full space-y-6">
        {/* Sub-tab 1: BIBR1532 Binding Pocket Residue Catalog */}
        {activeSubTab === 'bibr_pocket' && (
          <div className="space-y-4">
            <div className="flex items-center justify-between">
              <div>
                <h2 className="text-sm font-semibold text-[#F2F7FF] flex items-center gap-2">
                  <Flame className="w-4 h-4 text-[#FF7D45]" />
                  BIBR1532 Allosteric Pocket Contact Catalog (PDB 9Q14)
                </h2>
                <p className="text-xs text-[#91A6BE] mt-0.5">
                  Select any residue below to focus the 3D camera onto the TERT thumb/palm pocket occupied by BIBR1532.
                </p>
              </div>
              <button
                onClick={() => {
                  onFocusInhibitor();
                  onNavigateToTab('explore');
                }}
                className="px-3.5 py-1.5 text-xs font-mono font-bold rounded-lg bg-orange-600 hover:bg-orange-500 text-white shadow transition flex items-center gap-1.5"
              >
                <Crosshair className="w-3.5 h-3.5" />
                Focus Inhibitor in 3D
              </button>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
              {protein.experimentalInhibitor.keyContactResidues.map((res) => (
                <div
                  key={res.resi}
                  onClick={() => {
                    onFocusResidue({ resi: res.resi, chain: res.chain });
                    onSelectComponent('pocket');
                    onNavigateToTab('explore');
                  }}
                  className="p-4 rounded-xl bg-[#152237] border border-[#1e3250] hover:border-[#FF7D45] cursor-pointer transition group"
                >
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-2">
                      <span className="w-2.5 h-2.5 rounded-full bg-[#FF7D45] group-hover:scale-125 transition" />
                      <span className="text-sm font-mono font-bold text-[#F2F7FF]">
                        {res.resn} {res.resi}
                      </span>
                    </div>
                    <span className="text-[10px] font-mono px-2 py-0.5 rounded bg-[#0C1423] text-[#63E6DE]">
                      TERT Chain A
                    </span>
                  </div>
                  <p className="text-xs text-[#91A6BE] mt-2 leading-relaxed">
                    {res.role}
                  </p>
                  <div className="mt-3 pt-2 border-t border-[#1c2e4a] flex items-center justify-between text-[11px] font-mono text-[#5E7594]">
                    <span>Inhibitor interaction</span>
                    <span className="text-[#FF7D45] group-hover:underline flex items-center gap-1">
                      Focus 3D <Crosshair className="w-3 h-3" />
                    </span>
                  </div>
                </div>
              ))}
            </div>

            {/* Scientific Explanation Banner */}
            <div className="p-4 rounded-xl bg-[#152237]/80 border border-[#1e3250] flex items-start gap-3">
              <Shield className="w-5 h-5 text-[#63E6DE] flex-shrink-0 mt-0.5" />
              <div className="text-xs text-[#91A6BE] leading-relaxed space-y-1">
                <span className="font-semibold text-[#F2F7FF]">
                  Mechanism of BIBR1532 Allosteric Inhibition:
                </span>
                <p>
                  As shown in 9Q14, BIBR1532 binds non-competitively into a hydrophobic crevice formed by Val867, Phe870,
                  Leu977, and Met980 between the TERT thumb and palm domains. This wedges the thumb subdomain in an
                  inflexible state, inhibiting the processive repeat synthesis (RAP) essential for telomere elongation.
                </p>
              </div>
            </div>
          </div>
        )}

        {/* Sub-tab 2: Complex Subunits Catalog */}
        {activeSubTab === 'subunits' && (
          <div className="space-y-4">
            <div>
              <h2 className="text-sm font-semibold text-[#F2F7FF] flex items-center gap-2">
                <Layers className="w-4 h-4 text-[#A79BEE]" />
                Human Telomerase Ribonucleoprotein Subunits (9Q14)
              </h2>
              <p className="text-xs text-[#91A6BE] mt-0.5">
                Inspect each macromolecular entity within the 3.0 Å cryo-EM complex.
              </p>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              {protein.subunits.map((sub) => (
                <div
                  key={sub.id}
                  onClick={() => {
                    onSelectComponent(sub.id as SelectedComponentType);
                    onNavigateToTab('explore');
                  }}
                  className="p-4 rounded-xl bg-[#152237] border border-[#1e3250] hover:border-cyan-400/80 cursor-pointer transition space-y-2 group"
                >
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-2">
                      <span className="w-3 h-3 rounded-full" style={{ backgroundColor: sub.color }} />
                      <span className="text-sm font-bold text-[#F2F7FF]">{sub.name}</span>
                    </div>
                    <span className="text-[10px] font-mono px-2 py-0.5 rounded bg-[#0C1423] text-[#91A6BE]">
                      Chain {sub.chain}
                    </span>
                  </div>
                  <p className="text-xs text-[#91A6BE] leading-relaxed">{sub.description}</p>
                  <div className="pt-2 border-t border-[#1c2e4a] text-[11px] text-[#5E7594] flex items-center justify-between font-mono">
                    <span>{sub.lengthOrAtoms}</span>
                    <span className="text-[#63E6DE] group-hover:underline flex items-center gap-1">
                      Inspect in 3D <ArrowRight className="w-3 h-3" />
                    </span>
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Sub-tab 3: Backend Docking Grid Configurator */}
        {activeSubTab === 'grid' && (
          <div className="space-y-4">
            <div>
              <h2 className="text-sm font-semibold text-[#F2F7FF] flex items-center gap-2">
                <Crosshair className="w-4 h-4 text-[#438DFF]" />
                Backend Molecular Docking Pipeline Parameters (9Q14 Target)
              </h2>
              <p className="text-xs text-[#91A6BE] mt-0.5">
                Centralized grid box configuration ready for teammate computational docking jobs.
              </p>
            </div>

            <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
              <div className="lg:col-span-2 space-y-4">
                {/* Coordinates */}
                <div className="p-4 rounded-xl bg-[#152237] border border-[#1e3250] space-y-3">
                  <div className="flex items-center justify-between">
                    <h3 className="text-xs font-semibold text-[#F2F7FF] font-mono">
                      1. Search Box Center Coordinates (Å)
                    </h3>
                    <button
                      onClick={() => setBoxCenter({ x: 208.5, y: 226.3, z: 182.0 })}
                      className="text-[10px] text-[#FF7D45] hover:underline"
                    >
                      Reset to BIBR1532 Pocket
                    </button>
                  </div>
                  <div className="grid grid-cols-3 gap-3">
                    <div>
                      <label className="text-[11px] font-mono text-[#91A6BE]">Center X</label>
                      <input
                        type="number"
                        step="0.5"
                        value={boxCenter.x}
                        onChange={(e) => setBoxCenter({ ...boxCenter, x: parseFloat(e.target.value) || 0 })}
                        className="w-full mt-1 bg-[#0C1423] border border-[#1e3250] rounded px-3 py-1.5 text-xs font-mono text-[#F2F7FF] focus:border-[#438DFF] outline-none"
                      />
                    </div>
                    <div>
                      <label className="text-[11px] font-mono text-[#91A6BE]">Center Y</label>
                      <input
                        type="number"
                        step="0.5"
                        value={boxCenter.y}
                        onChange={(e) => setBoxCenter({ ...boxCenter, y: parseFloat(e.target.value) || 0 })}
                        className="w-full mt-1 bg-[#0C1423] border border-[#1e3250] rounded px-3 py-1.5 text-xs font-mono text-[#F2F7FF] focus:border-[#438DFF] outline-none"
                      />
                    </div>
                    <div>
                      <label className="text-[11px] font-mono text-[#91A6BE]">Center Z</label>
                      <input
                        type="number"
                        step="0.5"
                        value={boxCenter.z}
                        onChange={(e) => setBoxCenter({ ...boxCenter, z: parseFloat(e.target.value) || 0 })}
                        className="w-full mt-1 bg-[#0C1423] border border-[#1e3250] rounded px-3 py-1.5 text-xs font-mono text-[#F2F7FF] focus:border-[#438DFF] outline-none"
                      />
                    </div>
                  </div>
                </div>

                {/* Dimensions */}
                <div className="p-4 rounded-xl bg-[#152237] border border-[#1e3250] space-y-3">
                  <h3 className="text-xs font-semibold text-[#F2F7FF] font-mono">
                    2. Search Box Dimensions (Å)
                  </h3>
                  <div className="grid grid-cols-3 gap-3">
                    <div>
                      <label className="text-[11px] font-mono text-[#91A6BE]">Size X</label>
                      <input
                        type="number"
                        value={boxSize.x}
                        onChange={(e) => setBoxSize({ ...boxSize, x: parseFloat(e.target.value) || 20 })}
                        className="w-full mt-1 bg-[#0C1423] border border-[#1e3250] rounded px-3 py-1.5 text-xs font-mono text-[#F2F7FF] focus:border-[#438DFF] outline-none"
                      />
                    </div>
                    <div>
                      <label className="text-[11px] font-mono text-[#91A6BE]">Size Y</label>
                      <input
                        type="number"
                        value={boxSize.y}
                        onChange={(e) => setBoxSize({ ...boxSize, y: parseFloat(e.target.value) || 20 })}
                        className="w-full mt-1 bg-[#0C1423] border border-[#1e3250] rounded px-3 py-1.5 text-xs font-mono text-[#F2F7FF] focus:border-[#438DFF] outline-none"
                      />
                    </div>
                    <div>
                      <label className="text-[11px] font-mono text-[#91A6BE]">Size Z</label>
                      <input
                        type="number"
                        value={boxSize.z}
                        onChange={(e) => setBoxSize({ ...boxSize, z: parseFloat(e.target.value) || 20 })}
                        className="w-full mt-1 bg-[#0C1423] border border-[#1e3250] rounded px-3 py-1.5 text-xs font-mono text-[#F2F7FF] focus:border-[#438DFF] outline-none"
                      />
                    </div>
                  </div>
                </div>

                {/* Scoring Engine & Exhaustiveness */}
                <div className="p-4 rounded-xl bg-[#152237] border border-[#1e3250] space-y-3">
                  <h3 className="text-xs font-semibold text-[#F2F7FF] font-mono">
                    3. Scoring Engine & Exhaustiveness
                  </h3>
                  <div className="grid grid-cols-2 gap-4">
                    <div>
                      <label className="text-[11px] font-mono text-[#91A6BE]">Engine</label>
                      <select
                        value={scoringEngine}
                        onChange={(e) => setScoringEngine(e.target.value)}
                        className="w-full mt-1 bg-[#0C1423] border border-[#1e3250] rounded px-3 py-1.5 text-xs font-mono text-[#F2F7FF] outline-none"
                      >
                        <option value="AutoDock Vina v1.2.5">AutoDock Vina v1.2.5</option>
                        <option value="RF-Score v2 Ensemble">RF-Score v2 Ensemble</option>
                        <option value="Gnina CNN Deep Learning">Gnina CNN Deep Learning</option>
                      </select>
                    </div>
                    <div>
                      <div className="flex justify-between text-[11px] font-mono">
                        <span className="text-[#91A6BE]">Exhaustiveness</span>
                        <span className="text-[#63E6DE]">{exhaustiveness}</span>
                      </div>
                      <input
                        type="range"
                        min="8"
                        max="64"
                        step="8"
                        value={exhaustiveness}
                        onChange={(e) => setExhaustiveness(parseInt(e.target.value))}
                        className="w-full mt-2 accent-[#63E6DE]"
                      />
                    </div>
                  </div>
                </div>
              </div>

              {/* Execution status */}
              <div className="space-y-4">
                <div className="p-4 rounded-xl bg-[#152237] border border-[#1e3250] space-y-3">
                  <h3 className="text-xs font-semibold text-[#F2F7FF] font-mono">
                    Docking Pipeline Status
                  </h3>
                  <div className="space-y-2 text-xs">
                    <div className="flex justify-between py-1 border-b border-[#1c2e4a]">
                      <span className="text-[#91A6BE]">Target:</span>
                      <span className="font-mono text-[#F2F7FF]">Telomerase (9Q14)</span>
                    </div>
                    <div className="flex justify-between py-1 border-b border-[#1c2e4a]">
                      <span className="text-[#91A6BE]">Active Candidate:</span>
                      <span className="font-mono text-[#438DFF]">{currentCandidate.name}</span>
                    </div>
                    <div className="flex justify-between py-1 border-b border-[#1c2e4a]">
                      <span className="text-[#91A6BE]">Experimental Benchmark:</span>
                      <span className="font-mono text-[#FF7D45]">BIBR1532 (3.0 Å)</span>
                    </div>
                    <div className="flex justify-between py-1 border-b border-[#1c2e4a]">
                      <span className="text-[#91A6BE]">Backend Queue:</span>
                      <span className="font-mono text-amber-300">
                        {pipelineState === 'idle'
                          ? 'Awaiting Results'
                          : pipelineState === 'queued'
                          ? 'Job Queued...'
                          : 'Simulating...'}
                      </span>
                    </div>
                  </div>

                  <div className="pt-2">
                    <button
                      onClick={handleSimulateQueue}
                      disabled={pipelineState !== 'idle'}
                      className={`w-full py-2.5 px-3 rounded-lg text-xs font-mono font-medium flex items-center justify-center gap-2 transition ${
                        pipelineState === 'idle'
                          ? 'bg-[#438DFF] hover:bg-[#3476dc] text-white shadow-md'
                          : 'bg-[#1c2e4a] text-[#91A6BE] cursor-wait'
                      }`}
                    >
                      {pipelineState === 'idle' ? (
                        <>
                          <Play className="w-3.5 h-3.5" />
                          Simulate Pipeline Queue
                        </>
                      ) : (
                        <>
                          <Clock className="w-3.5 h-3.5 animate-spin text-[#63E6DE]" />
                          Connecting to Backend...
                        </>
                      )}
                    </button>
                  </div>
                </div>

                <div className="p-4 rounded-xl bg-[#0C1423] border border-[#1e3250] space-y-2 text-xs">
                  <div className="flex items-center gap-1.5 text-[#63E6DE] font-semibold">
                    <FilePlus className="w-3.5 h-3.5" />
                    Record in Notes
                  </div>
                  <p className="text-[11px] text-[#91A6BE]">
                    Log the chosen search box configuration to your research notes before running the cluster job.
                  </p>
                  <button
                    onClick={() => {
                      onAddNote(
                        'Hypothesis',
                        `Configured grid box centered on 9Q14 BIBR1532 allosteric pocket at [${boxCenter.x}, ${boxCenter.y}, ${boxCenter.z}] with dimensions [${boxSize.x}, ${boxSize.y}, ${boxSize.z}] Å for ${currentCandidate.name}. Probing allosteric pocket shape complementarity against TERT Phe870 and Leu977.`
                      );
                      onNavigateToTab('notes');
                    }}
                    className="w-full py-1.5 rounded bg-[#152237] hover:bg-[#1c2e4a] text-[#F2F7FF] font-mono text-[11px] border border-[#1e3250] transition"
                  >
                    Save Config to Lab Notes
                  </button>
                </div>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
};
