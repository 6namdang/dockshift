/**
 * @license
 * SPDX-License-Identifier: Apache-2.0
 */

import React, { useState } from 'react';
import {
  ExternalLink,
  Clock,
  Layers,
  ArrowRight,
  Eye,
  EyeOff,
  Crosshair,
  Flame,
  FileText,
  ChevronDown,
  ChevronUp,
  Info
} from 'lucide-react';
import { Protein, Ligand, DockingResult, ComponentVisibility, SelectedComponentType } from '../types/docking';

interface MolecularInspectorProps {
  protein: Protein;
  selectedComponent: SelectedComponentType;
  onSelectComponent: (component: SelectedComponentType) => void;
  visibility: ComponentVisibility;
  onToggleVisibility: (key: keyof ComponentVisibility) => void;
  onFocusInhibitor: () => void;
  candidates: Ligand[];
  selectedCandidateId: string;
  onSelectCandidate: (candidateId: string) => void;
  dockingResults: Record<string, DockingResult>;
  onAddNoteForCandidate: (candidateId: string) => void;
}

export const MolecularInspector: React.FC<MolecularInspectorProps> = ({
  protein,
  selectedComponent,
  onSelectComponent,
  visibility,
  onToggleVisibility,
  onFocusInhibitor,
  candidates,
  selectedCandidateId,
  onSelectCandidate,
  dockingResults,
  onAddNoteForCandidate
}) => {
  const [showStructuralDetails, setShowStructuralDetails] = useState<boolean>(false);
  const [showCandidateSection, setShowCandidateSection] = useState<boolean>(false);

  const defaultCandidate: Ligand = {
    id: 'bibr1532',
    name: 'BIBR1532',
    chemicalFormula: 'C21H17NO3',
    molecularWeight: 331.36,
    description: 'Experimentally solved inhibitor (PDB 9Q14).',
    tag: 'Reference Ligand',
    targetSite: 'TERT Thumb/Palm Pocket'
  };

  const currentCandidate =
    candidates && candidates.length > 0
      ? candidates.find((c) => c.id === selectedCandidateId) || candidates[0]
      : defaultCandidate;

  const defaultSubunit = {
    id: 'inhibitor',
    name: 'BIBR1532 Inhibitor',
    type: 'inhibitor' as const,
    chain: 'G',
    authChain: 'A',
    resn: '55C',
    color: '#FF7D45',
    description: 'Non-competitive small-molecule inhibitor of human telomerase. Experimentally resolved bound in the TERT thumb/palm crevice.',
    role: 'Blocks repeat addition processivity without competing with nucleotides or RNA.',
    lengthOrAtoms: 'C21H17NO3 (MW: 331.36 g/mol)',
    keyFeatures: [
      'Resolved experimentally in Cryo-EM at 3.0 Å (PDB: 9Q14)',
      'Hydrophobic contacts with TERT Phe870, Leu977, Met980'
    ]
  };

  const selectedSubunit =
    protein?.subunits?.find((s) => s.id === selectedComponent) ||
    protein?.subunits?.[3] ||
    protein?.subunits?.[0] ||
    defaultSubunit;

  const isExperimental = selectedSubunit.id === 'inhibitor' || selectedSubunit.id === 'tert' || selectedSubunit.id === 'terc' || selectedSubunit.id === 'dna';

  return (
    <aside
      aria-label="Molecular Inspector"
      className="w-[300px] flex-shrink-0 h-full bg-[#18232D] border-l border-[#202F3C] flex flex-col text-[#E9F0F3] overflow-y-auto select-none z-20 text-xs"
    >
      {/* 1. Inspector Header: Structure & Evidence Status */}
      <div className="p-3.5 border-b border-[#202F3C] bg-[#0B1118]/60 space-y-1.5">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-1.5">
            <span className="font-semibold text-xs text-[#E9F0F3]">Human Telomerase</span>
            <span className="text-[10px] font-mono text-[#90A4AF]">PDB 9Q14</span>
          </div>
          <span className="text-[10px] font-mono px-1.5 py-0.2 rounded bg-[#0B1118] text-[#59C9C0] border border-[#202F3C]">
            3.0 Å Cryo-EM
          </span>
        </div>

        <p className="text-[11px] text-[#90A4AF] leading-snug">
          Catalytic core complexed with RNA template, DNA substrate, and BIBR1532.
        </p>
      </div>

      <div className="p-3.5 space-y-3.5 flex-1">
        {/* 2. Component Navigation Buttons */}
        <section className="space-y-1.5">
          <div className="text-[10px] font-mono text-[#90A4AF] uppercase tracking-wider">
            Complex Components
          </div>
          <div className="grid grid-cols-2 gap-1.5">
            {protein.subunits.map((subunit) => {
              const isSelected = selectedComponent === subunit.id;
              const isVisible =
                subunit.id === 'tert'
                  ? visibility.showProtein
                  : subunit.id === 'terc'
                  ? visibility.showRna
                  : subunit.id === 'dna'
                  ? visibility.showDna
                  : visibility.showInhibitor;

              return (
                <div
                  key={subunit.id}
                  onClick={() => onSelectComponent(subunit.id as SelectedComponentType)}
                  className={`p-2 rounded-xl border cursor-pointer transition flex items-center justify-between ${
                    isSelected
                      ? 'bg-[#1E2D3A] border-[#59C9C0] text-[#E9F0F3] shadow-sm'
                      : 'bg-[#0B1118]/80 border-[#202F3C] text-[#90A4AF] hover:text-[#E9F0F3]'
                  }`}
                >
                  <div className="flex items-center gap-1.5 min-w-0">
                    <span
                      className="w-2 h-2 rounded-full flex-shrink-0"
                      style={{ backgroundColor: subunit.color }}
                    />
                    <span className="text-[11px] font-medium truncate">
                      {subunit.name.split(' ')[0]}
                    </span>
                  </div>

                  <button
                    onClick={(e) => {
                      e.stopPropagation();
                      if (subunit.id === 'tert') onToggleVisibility('showProtein');
                      else if (subunit.id === 'terc') onToggleVisibility('showRna');
                      else if (subunit.id === 'dna') onToggleVisibility('showDna');
                      else onToggleVisibility('showInhibitor');
                    }}
                    title={isVisible ? `Hide ${subunit.name}` : `Show ${subunit.name}`}
                    className={`p-0.5 rounded transition ${
                      isVisible ? 'text-[#59C9C0]' : 'text-[#627783] line-through'
                    }`}
                  >
                    {isVisible ? <Eye className="w-3 h-3" /> : <EyeOff className="w-3 h-3" />}
                  </button>
                </div>
              );
            })}
          </div>
        </section>

        {/* 3. Selected Component Hero Card */}
        <section className="p-3 rounded-xl bg-[#0B1118]/80 border border-[#202F3C] space-y-2">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <span
                className="w-2.5 h-2.5 rounded-full"
                style={{ backgroundColor: selectedSubunit.color }}
              />
              <span className="font-semibold text-xs text-[#E9F0F3]">
                {selectedSubunit.name}
              </span>
            </div>
            <span
              className={`text-[9px] font-mono px-1.5 py-0.2 rounded border ${
                isExperimental
                  ? 'bg-emerald-950/40 text-emerald-400 border-emerald-800/40'
                  : 'bg-[#1E2D3A] text-[#90A4AF] border-[#202F3C]'
              }`}
            >
              {isExperimental ? 'Observed (9Q14)' : 'Predicted'}
            </span>
          </div>

          <p className="text-[11px] text-[#90A4AF] leading-relaxed">
            {selectedSubunit.description}
          </p>

          <div className="pt-1.5 border-t border-[#202F3C] text-[11px] text-[#E9F0F3]">
            <span className="text-[#90A4AF] text-[10px] block">Mechanistic Role:</span>
            {selectedSubunit.role}
          </div>

          {selectedSubunit.id === 'inhibitor' && (
            <button
              onClick={onFocusInhibitor}
              className="w-full mt-1 py-1.5 px-3 rounded-lg bg-[#E9A76A]/20 hover:bg-[#E9A76A]/30 text-[#E9A76A] border border-[#E9A76A]/30 text-xs font-medium transition flex items-center justify-center gap-1.5 cursor-pointer"
            >
              <Crosshair className="w-3.5 h-3.5" />
              <span>Center Inhibitor Pocket</span>
            </button>
          )}
        </section>

        {/* 4. Expandable Structural Details */}
        <section className="border border-[#202F3C] rounded-xl overflow-hidden bg-[#0B1118]/50">
          <button
            onClick={() => setShowStructuralDetails(!showStructuralDetails)}
            className="w-full p-2.5 flex items-center justify-between text-left text-xs text-[#90A4AF] hover:text-[#E9F0F3] transition cursor-pointer"
          >
            <span className="font-medium">Structural Details &amp; Contacts</span>
            {showStructuralDetails ? (
              <ChevronUp className="w-3.5 h-3.5 text-[#627783]" />
            ) : (
              <ChevronDown className="w-3.5 h-3.5 text-[#627783]" />
            )}
          </button>

          {showStructuralDetails && (
            <div className="p-3 pt-0 border-t border-[#202F3C]/50 space-y-2 text-[11px]">
              <div className="flex justify-between text-[#90A4AF]">
                <span>Chain Identifier:</span>
                <span className="font-mono text-[#E9F0F3]">Chain {selectedSubunit.chain}</span>
              </div>
              {selectedSubunit.lengthOrAtoms && (
                <div className="flex justify-between text-[#90A4AF]">
                  <span>Formula / Length:</span>
                  <span className="font-mono text-[#E9F0F3]">{selectedSubunit.lengthOrAtoms}</span>
                </div>
              )}

              {selectedSubunit.keyFeatures && (
                <div className="space-y-1 pt-1 border-t border-[#202F3C]/50">
                  <span className="text-[10px] text-[#90A4AF] block">Key Interactions:</span>
                  <ul className="space-y-1 text-[10px] text-[#90A4AF]">
                    {selectedSubunit.keyFeatures.map((feat, i) => (
                      <li key={i} className="flex items-start gap-1">
                        <span className="text-[#59C9C0]">•</span>
                        <span>{feat}</span>
                      </li>
                    ))}
                  </ul>
                </div>
              )}
            </div>
          )}
        </section>

        {/* 5. Expandable Pipeline Candidates Inspection */}
        <section className="border border-[#202F3C] rounded-xl overflow-hidden bg-[#0B1118]/50">
          <button
            onClick={() => setShowCandidateSection(!showCandidateSection)}
            className="w-full p-2.5 flex items-center justify-between text-left text-xs text-[#90A4AF] hover:text-[#E9F0F3] transition cursor-pointer"
          >
            <span className="font-medium">Screening Candidates ({candidates.length})</span>
            {showCandidateSection ? (
              <ChevronUp className="w-3.5 h-3.5 text-[#627783]" />
            ) : (
              <ChevronDown className="w-3.5 h-3.5 text-[#627783]" />
            )}
          </button>

          {showCandidateSection && (
            <div className="p-3 pt-0 border-t border-[#202F3C]/50 space-y-2 text-[11px]">
              <div className="grid grid-cols-2 gap-1 pt-1">
                {candidates.slice(0, 4).map((cand) => (
                  <button
                    key={cand.id}
                    onClick={() => onSelectCandidate(cand.id)}
                    className={`p-1.5 rounded-lg border text-left transition cursor-pointer ${
                      selectedCandidateId === cand.id
                        ? 'bg-[#1E2D3A] border-[#59C9C0] text-[#E9F0F3]'
                        : 'bg-[#0B1118] border-[#202F3C] text-[#90A4AF] hover:text-[#E9F0F3]'
                    }`}
                  >
                    <div className="font-semibold truncate text-[11px]">{cand.name}</div>
                    <div className="text-[9px] text-[#627783]">{cand.tag}</div>
                  </button>
                ))}
              </div>

              {currentCandidate && (
                <div className="p-2 rounded-lg bg-[#0B1118] border border-[#202F3C] space-y-1">
                  <div className="flex justify-between font-semibold text-[#E9F0F3]">
                    <span>{currentCandidate.name}</span>
                    <span className="text-[#59C9C0] font-mono text-[10px]">
                      {currentCandidate.prediction?.predicted_pic50
                        ? `pIC50 ${currentCandidate.prediction.predicted_pic50.toFixed(2)}`
                        : '—'}
                    </span>
                  </div>
                  <div className="text-[10px] text-[#90A4AF]">
                    {currentCandidate.prediction?.domain === 'in' ? 'Inside applicability domain' : 'Outside domain (extrapolation)'}
                  </div>
                </div>
              )}

              <div className="flex items-center gap-1.5 pt-1">
                <></>
                <button
                  onClick={() => onAddNoteForCandidate(currentCandidate.id)}
                  title="Add Note for Candidate"
                  className="p-1.5 rounded-lg bg-[#0B1118] hover:bg-[#1E2D3A] text-[#90A4AF] hover:text-[#E9F0F3] border border-[#202F3C] transition cursor-pointer"
                >
                  <FileText className="w-3.5 h-3.5" />
                </button>
              </div>
            </div>
          )}
        </section>
      </div>
    </aside>
  );
};
