/**
 * @license
 * SPDX-License-Identifier: Apache-2.0
 */

import React, { useState, useEffect } from 'react';
import {
  Sparkles,
  Crosshair,
  CheckCircle2,
  HelpCircle,
  RotateCcw,
  BookOpen,
  ArrowRight,
  Shield,
  Layers,
  Award,
  ChevronRight,
  Eye,
  Info,
  ExternalLink,
  Flame,
  X
} from 'lucide-react';
import { Ligand, SelectedComponentType } from '../types/docking';

interface PlaygroundChallengeProps {
  selectedComponent: SelectedComponentType;
  onSelectComponent: (component: SelectedComponentType) => void;
  onFocusInhibitor: () => void;
  onAddNote: (
    category: 'Observation' | 'Question' | 'Hypothesis' | 'Next Experiment',
    content: string,
    title?: string
  ) => void;
  onNavigateToTab?: (tab: string) => void;
  candidates: Ligand[];
  isOpen: boolean;
  onClose: () => void;
}

export const PlaygroundChallenge: React.FC<PlaygroundChallengeProps> = ({
  selectedComponent,
  onSelectComponent,
  onFocusInhibitor,
  onAddNote,
  onNavigateToTab,
  candidates,
  isOpen,
  onClose
}) => {
  const [currentStage, setCurrentStage] = useState<1 | 2 | 3 | 4>(1);
  const [showPartExplanation, setShowPartExplanation] = useState(false);
  const [showHint, setShowHint] = useState(false);
  const [hasFoundInhibitor, setHasFoundInhibitor] = useState(false);
  const [wrongSelectionFeedback, setWrongSelectionFeedback] = useState<string | null>(null);
  const [selectedReflection, setSelectedReflection] = useState<number | null>(null);
  const [reflectionSaved, setReflectionSaved] = useState(false);

  // Candidate comparison state
  const [candidateAId, setCandidateAId] = useState<string>('bibr1532');
  const [candidateBId, setCandidateBId] = useState<string>(
    candidates.find((c) => c.id !== 'bibr1532')?.id || 'mst-312'
  );

  // Check whenever selectedComponent changes
  useEffect(() => {
    if (currentStage === 2) {
      if (selectedComponent === 'inhibitor') {
        setHasFoundInhibitor(true);
        setWrongSelectionFeedback(null);
      } else if (selectedComponent !== 'all') {
        const labels: Record<string, string> = {
          tert: 'TERT Catalytic Protein (Cyan)',
          terc: 'Telomerase RNA Template / TERC (Violet)',
          dna: 'Telomeric DNA Substrate (Gold)',
          pocket: 'TERT Thumb/Palm Pocket Region'
        };
        setWrongSelectionFeedback(
          `You selected ${labels[selectedComponent] || selectedComponent}. That is an essential part of the enzyme, but not the small-molecule inhibitor BIBR1532. Look closely for the orange small molecule in the crevice!`
        );
      }
    }
  }, [selectedComponent, currentStage]);

  if (!isOpen) return null;

  const candidateA = candidates.find((c) => c.id === candidateAId) || candidates[0];
  const candidateB = candidates.find((c) => c.id === candidateBId) || candidates[1] || candidates[0];

  const handleResetChallenge = () => {
    setCurrentStage(1);
    setHasFoundInhibitor(false);
    setWrongSelectionFeedback(null);
    setShowHint(false);
    setSelectedReflection(null);
    setReflectionSaved(false);
    onSelectComponent('all');
  };

  const handleSaveReflection = () => {
    const questions = [
      'Whether it is toxic to healthy dividing cells or inhibits other essential polymerases.',
      'How well it gets absorbed and survives in the human body without premature breakdown (pharmacokinetics).',
      'Whether cancer cells can develop resistance mutations in the TERT binding crevice.',
      'All of the above — drug discovery requires testing selectivity, toxicity, stability, and in vivo efficacy.'
    ];

    const chosenText = selectedReflection != null ? questions[selectedReflection] : questions[3];
    const noteText =
      `Playground Challenge 01 Reflection: Drug Discovery Considerations for BIBR1532\n\n` +
      `Player Answer: "${chosenText}"\n\n` +
      `Scientific Insight: Binding to human telomerase (PDB 9Q14) is only the foundational proof of mechanism. Before an inhibitor becomes a therapeutic candidate, computational and wet-lab teams must evaluate selectivity across DNA/RNA polymerases, cellular permeability, metabolic stability, and vulnerability to resistance mutations in TERT residues Phe870 and Leu977.`;

    onAddNote('Question', noteText, 'Playground Reflection: BIBR1532 Drug Potential');
    setReflectionSaved(true);
  };

  return (
    <div className="absolute top-4 left-4 z-40 max-w-md w-full bg-[#18232D]/95 backdrop-blur-md rounded-2xl border border-[#202F3C] shadow-2xl text-[#E9F0F3] overflow-hidden transition-all duration-200 select-none">
      {/* Header bar */}
      <div className="px-4 py-3 bg-[#0B1118]/80 border-b border-[#202F3C] flex items-center justify-between">
        <div className="flex items-center gap-2">
          <div className="w-6 h-6 rounded-lg bg-[#59C9C0]/20 text-[#59C9C0] flex items-center justify-center font-bold text-xs">
            🎮
          </div>
          <div>
            <h2 className="text-xs font-bold text-[#E9F0F3] flex items-center gap-1.5">
              Playground Challenge 01
              <span className="text-[10px] font-normal text-[#59C9C0] px-1.5 py-0.2 rounded bg-[#59C9C0]/10 border border-[#59C9C0]/20">
                Beginner Mode
              </span>
            </h2>
            <div className="text-[10px] text-[#90A4AF]">Find the Inhibitor</div>
          </div>
        </div>

        <div className="flex items-center gap-2">
          <button
            onClick={handleResetChallenge}
            title="Restart Challenge"
            className="p-1 rounded-lg text-[#90A4AF] hover:text-[#E9F0F3] hover:bg-[#202F3C] transition cursor-pointer"
          >
            <RotateCcw className="w-3.5 h-3.5" />
          </button>
          <button
            onClick={onClose}
            title="Close Challenge (Return to standard inspector)"
            className="p-1 rounded-lg text-[#90A4AF] hover:text-[#E9F0F3] hover:bg-[#202F3C] transition cursor-pointer"
          >
            <X className="w-4 h-4" />
          </button>
        </div>
      </div>

      {/* Progress Stepper */}
      <div className="grid grid-cols-4 border-b border-[#202F3C] text-[10px] font-mono text-center">
        <button
          onClick={() => setCurrentStage(1)}
          className={`py-1.5 border-r border-[#202F3C] transition cursor-pointer ${
            currentStage === 1
              ? 'bg-[#1E2D3A] text-[#59C9C0] font-bold'
              : 'text-[#627783] hover:text-[#90A4AF]'
          }`}
        >
          1. Explore
        </button>
        <button
          onClick={() => setCurrentStage(2)}
          className={`py-1.5 border-r border-[#202F3C] transition cursor-pointer ${
            currentStage === 2
              ? 'bg-[#1E2D3A] text-[#59C9C0] font-bold'
              : hasFoundInhibitor
              ? 'text-[#59C9C0]'
              : 'text-[#627783] hover:text-[#90A4AF]'
          }`}
        >
          2. Find {hasFoundInhibitor && '✓'}
        </button>
        <button
          onClick={() => hasFoundInhibitor && setCurrentStage(3)}
          disabled={!hasFoundInhibitor}
          className={`py-1.5 border-r border-[#202F3C] transition cursor-pointer ${
            currentStage === 3
              ? 'bg-[#1E2D3A] text-[#59C9C0] font-bold'
              : reflectionSaved
              ? 'text-[#59C9C0]'
              : 'text-[#627783] disabled:opacity-40'
          }`}
        >
          3. Reflect {reflectionSaved && '✓'}
        </button>
        <button
          onClick={() => hasFoundInhibitor && setCurrentStage(4)}
          disabled={!hasFoundInhibitor}
          className={`py-1.5 transition cursor-pointer ${
            currentStage === 4
              ? 'bg-[#1E2D3A] text-[#59C9C0] font-bold'
              : 'text-[#627783] disabled:opacity-40'
          }`}
        >
          4. Compare
        </button>
      </div>

      {/* Stage Body */}
      <div className="p-4 space-y-3.5 max-h-[70vh] overflow-y-auto">
        {/* STAGE 1: EXPLORE */}
        {currentStage === 1 && (
          <div className="space-y-3">
            <div className="p-3 rounded-xl bg-[#0B1118]/80 border border-[#202F3C] space-y-2">
              <p className="text-xs text-[#E9F0F3] leading-relaxed font-normal">
                Meet <strong className="text-[#59C9C0] font-semibold">telomerase</strong>, a molecular machine that extends and protects the caps at chromosome ends.
              </p>
              <p className="text-[11px] text-[#90A4AF] leading-relaxed">
                Cancer cells frequently hijack telomerase to achieve unlimited replication. Try rotating (click and drag) and zooming (scroll) the real experimental 3D structure (PDB 9Q14).
              </p>
            </div>

            {/* Optional Subunit Breakdown */}
            <div>
              <button
                onClick={() => setShowPartExplanation(!showPartExplanation)}
                className="w-full py-1.5 px-3 rounded-lg bg-[#1E2D3A] hover:bg-[#243746] text-xs text-[#90A4AF] hover:text-[#E9F0F3] flex items-center justify-between transition cursor-pointer border border-[#202F3C]"
              >
                <span>{showPartExplanation ? 'Hide subunit guide' : 'Optional: Learn the 3 main parts'}</span>
                <ChevronRight className={`w-3.5 h-3.5 transition-transform ${showPartExplanation ? 'rotate-90' : ''}`} />
              </button>

              {showPartExplanation && (
                <div className="mt-2 space-y-1.5 p-3 rounded-xl bg-[#0B1118]/70 border border-[#202F3C] text-[11px]">
                  <div
                    onClick={() => onSelectComponent('tert')}
                    className="p-1.5 rounded-lg hover:bg-[#18232D] cursor-pointer flex items-center justify-between"
                  >
                    <div className="flex items-center gap-2">
                      <span className="w-2.5 h-2.5 rounded-sm bg-[#59C9C0]" />
                      <span className="text-[#E9F0F3] font-medium">TERT (Protein Engine)</span>
                    </div>
                    <span className="text-[10px] text-[#90A4AF]">Catalytic Core</span>
                  </div>

                  <div
                    onClick={() => onSelectComponent('terc')}
                    className="p-1.5 rounded-lg hover:bg-[#18232D] cursor-pointer flex items-center justify-between"
                  >
                    <div className="flex items-center gap-2">
                      <span className="w-2.5 h-2.5 rounded-sm bg-[#A79BEE]" />
                      <span className="text-[#A79BEE] font-medium">TERC (RNA Guide)</span>
                    </div>
                    <span className="text-[10px] text-[#90A4AF]">Template</span>
                  </div>

                  <div
                    onClick={() => onSelectComponent('dna')}
                    className="p-1.5 rounded-lg hover:bg-[#18232D] cursor-pointer flex items-center justify-between"
                  >
                    <div className="flex items-center gap-2">
                      <span className="w-2.5 h-2.5 rounded-sm bg-[#E9A76A]" />
                      <span className="text-[#E9A76A] font-medium">Telomeric DNA</span>
                    </div>
                    <span className="text-[10px] text-[#90A4AF]">Substrate</span>
                  </div>
                </div>
              )}
            </div>

            <button
              onClick={() => setCurrentStage(2)}
              className="w-full py-2.5 px-4 rounded-xl bg-[#59C9C0] hover:bg-[#4EBEA4] text-[#0B1118] font-semibold text-xs transition flex items-center justify-center gap-2 shadow-md cursor-pointer"
            >
              <span>Start Challenge: Find the Inhibitor</span>
              <ArrowRight className="w-4 h-4" />
            </button>
          </div>
        )}

        {/* STAGE 2: FIND */}
        {currentStage === 2 && (
          <div className="space-y-3">
            <div className="p-3 rounded-xl bg-[#0B1118]/80 border border-[#202F3C] space-y-1.5">
              <div className="text-[10px] font-mono uppercase text-[#E9A76A] tracking-wider font-semibold">
                Mission Objective
              </div>
              <h3 className="text-xs font-bold text-[#E9F0F3] leading-snug">
                Can you find BIBR1532, a small molecule observed bound to telomerase?
              </h3>
              <p className="text-[11px] text-[#90A4AF] leading-relaxed">
                Click the inhibitor directly inside the 3D viewer, or select it from the component options below.
              </p>
            </div>

            {/* Component Selector Buttons */}
            <div className="space-y-1.5">
              <div className="text-[10px] font-mono text-[#90A4AF] uppercase tracking-wider">
                Select Observed Component:
              </div>
              <div className="grid grid-cols-2 gap-1.5">
                <button
                  onClick={() => onSelectComponent('tert')}
                  className={`py-2 px-2.5 rounded-xl border text-left text-xs transition cursor-pointer flex items-center gap-2 ${
                    selectedComponent === 'tert'
                      ? 'bg-[#1E2D3A] border-[#59C9C0] text-[#59C9C0]'
                      : 'bg-[#0B1118] border-[#202F3C] text-[#90A4AF] hover:text-[#E9F0F3]'
                  }`}
                >
                  <span className="w-2 h-2 rounded-full bg-[#59C9C0]" />
                  <span>TERT Protein</span>
                </button>

                <button
                  onClick={() => onSelectComponent('terc')}
                  className={`py-2 px-2.5 rounded-xl border text-left text-xs transition cursor-pointer flex items-center gap-2 ${
                    selectedComponent === 'terc'
                      ? 'bg-[#1E2D3A] border-[#A79BEE] text-[#A79BEE]'
                      : 'bg-[#0B1118] border-[#202F3C] text-[#90A4AF] hover:text-[#E9F0F3]'
                  }`}
                >
                  <span className="w-2 h-2 rounded-full bg-[#A79BEE]" />
                  <span>TERC RNA</span>
                </button>

                <button
                  onClick={() => onSelectComponent('dna')}
                  className={`py-2 px-2.5 rounded-xl border text-left text-xs transition cursor-pointer flex items-center gap-2 ${
                    selectedComponent === 'dna'
                      ? 'bg-[#1E2D3A] border-[#E9A76A] text-[#E9A76A]'
                      : 'bg-[#0B1118] border-[#202F3C] text-[#90A4AF] hover:text-[#E9F0F3]'
                  }`}
                >
                  <span className="w-2 h-2 rounded-full bg-[#E9A76A]" />
                  <span>DNA Substrate</span>
                </button>

                <button
                  onClick={() => onSelectComponent('inhibitor')}
                  className={`py-2 px-2.5 rounded-xl border text-left text-xs transition cursor-pointer flex items-center gap-2 ${
                    selectedComponent === 'inhibitor'
                      ? 'bg-[#FF7D45]/20 border-[#FF7D45] text-[#FF7D45] font-bold shadow-sm'
                      : 'bg-[#0B1118] border-[#202F3C] text-[#90A4AF] hover:text-[#E9F0F3]'
                  }`}
                >
                  <span className="w-2 h-2 rounded-full bg-[#FF7D45]" />
                  <span>BIBR1532</span>
                </button>
              </div>
            </div>

            {/* Wrong Selection Feedback */}
            {wrongSelectionFeedback && !hasFoundInhibitor && (
              <div className="p-2.5 rounded-xl bg-amber-950/40 border border-amber-800/40 text-[11px] text-amber-200 leading-snug space-y-1">
                <p>{wrongSelectionFeedback}</p>
                <div className="flex gap-2 pt-1">
                  <button
                    onClick={() => {
                      setWrongSelectionFeedback(null);
                      onSelectComponent('all');
                    }}
                    className="text-[10px] font-mono underline hover:text-white cursor-pointer"
                  >
                    Try Again
                  </button>
                  <span className="text-[#627783]">•</span>
                  <button
                    onClick={() => setShowHint(true)}
                    className="text-[10px] font-mono underline hover:text-white cursor-pointer"
                  >
                    Show Hint
                  </button>
                </div>
              </div>
            )}

            {/* Assistance tools: Hint & Focus on Inhibitor */}
            <div className="flex items-center gap-2 pt-1">
              <button
                onClick={() => setShowHint(!showHint)}
                className="flex-1 py-1.5 px-2.5 rounded-lg bg-[#1E2D3A] hover:bg-[#243746] text-xs font-mono text-[#90A4AF] hover:text-[#E9F0F3] border border-[#202F3C] transition flex items-center justify-center gap-1.5 cursor-pointer"
              >
                <HelpCircle className="w-3.5 h-3.5" />
                <span>{showHint ? 'Hide Hint' : 'Need a Hint?'}</span>
              </button>

              <button
                onClick={() => {
                  onFocusInhibitor();
                  onSelectComponent('inhibitor');
                }}
                className="py-1.5 px-3 rounded-lg bg-[#E9A76A]/20 hover:bg-[#E9A76A]/30 text-[#E9A76A] border border-[#E9A76A]/30 text-xs font-mono font-medium transition flex items-center gap-1.5 cursor-pointer"
              >
                <Crosshair className="w-3.5 h-3.5" />
                <span>Focus Camera on Pocket</span>
              </button>
            </div>

            {showHint && (
              <div className="p-2.5 rounded-xl bg-[#0B1118]/90 border border-[#202F3C] text-[11px] text-[#90A4AF] leading-relaxed">
                💡 <strong className="text-[#E9F0F3]">Hint:</strong> BIBR1532 is represented in <strong className="text-[#FF7D45]">orange sticks</strong>. It binds in an allosteric pocket located between the thumb and palm subdomains of the TERT protein.
              </div>
            )}

            {/* Success Banner when found */}
            {hasFoundInhibitor && (
              <div className="p-3.5 rounded-xl bg-emerald-950/50 border border-emerald-600/40 text-emerald-200 space-y-2">
                <div className="flex items-center gap-2 font-bold text-xs text-emerald-300">
                  <CheckCircle2 className="w-4 h-4 text-emerald-400" />
                  <span>Target Found! BIBR1532 Located.</span>
                </div>
                <p className="text-[11px] text-emerald-100/90 leading-relaxed font-normal">
                  You discovered BIBR1532 bound in the allosteric pocket of human telomerase resolved at 3.0 Å Cryo-EM resolution (PDB 9Q14).
                </p>
                <button
                  onClick={() => setCurrentStage(3)}
                  className="w-full py-2 px-3 rounded-lg bg-emerald-500 hover:bg-emerald-400 text-[#0B1118] font-bold text-xs transition flex items-center justify-center gap-1.5 shadow cursor-pointer mt-1"
                >
                  <span>Proceed to Stage 3: Scientific Reflection</span>
                  <ArrowRight className="w-3.5 h-3.5" />
                </button>
              </div>
            )}
          </div>
        )}

        {/* STAGE 3: REFLECT */}
        {currentStage === 3 && (
          <div className="space-y-3">
            <div className="p-3 rounded-xl bg-[#0B1118]/80 border border-[#202F3C] space-y-1.5">
              <div className="text-[10px] font-mono uppercase text-[#59C9C0] tracking-wider font-semibold">
                Stage 3: Scientific Reflection
              </div>
              <h3 className="text-xs font-bold text-[#E9F0F3] leading-snug">
                What might scientists need to investigate before concluding that this molecule could be a useful drug?
              </h3>
            </div>

            {/* Multiple Choice Options */}
            <div className="space-y-1.5">
              {[
                {
                  id: 0,
                  text: 'Whether it is toxic to healthy dividing cells or inhibits other essential polymerases.'
                },
                {
                  id: 1,
                  text: 'How well it gets absorbed and survives in the human body without premature breakdown (pharmacokinetics).'
                },
                {
                  id: 2,
                  text: 'Whether cancer cells can develop resistance mutations in the TERT binding crevice.'
                },
                {
                  id: 3,
                  text: 'All of the above — drug discovery requires testing selectivity, toxicity, stability, and in vivo efficacy.'
                }
              ].map((opt) => (
                <button
                  key={opt.id}
                  onClick={() => setSelectedReflection(opt.id)}
                  className={`w-full p-2.5 rounded-xl border text-left text-xs transition cursor-pointer flex items-start gap-2.5 ${
                    selectedReflection === opt.id
                      ? 'bg-[#1E2D3A] border-[#59C9C0] text-[#E9F0F3]'
                      : 'bg-[#0B1118] border-[#202F3C] text-[#90A4AF] hover:text-[#E9F0F3]'
                  }`}
                >
                  <span
                    className={`w-4 h-4 rounded-full flex-shrink-0 flex items-center justify-center text-[10px] font-mono mt-0.5 ${
                      selectedReflection === opt.id
                        ? 'bg-[#59C9C0] text-[#0B1118] font-bold'
                        : 'border border-[#202F3C] text-[#627783]'
                    }`}
                  >
                    {String.fromCharCode(65 + opt.id)}
                  </span>
                  <span className="leading-snug">{opt.text}</span>
                </button>
              ))}
            </div>

            {/* Explanation & Save action */}
            {selectedReflection !== null && (
              <div className="space-y-2 pt-1">
                <div className="p-3 rounded-xl bg-[#0B1118]/80 border border-[#202F3C] text-[11px] text-[#90A4AF] leading-relaxed space-y-1">
                  <div className="text-[#59C9C0] font-semibold">Scientific Rationale:</div>
                  <p>
                    {selectedReflection === 3
                      ? 'Exactly right! Target binding in a cryo-EM structure is just the starting milestone. Real medicines must be selective (not poison non-cancerous cells), bioavailable (survive liver metabolism and reach the tumor), and resilient against resistance mutations.'
                      : 'A critical consideration! In fact, all of these factors—selectivity, bioavailability, stability, and potential resistance—must be rigorously verified before a candidate advances to animal models or clinical trials.'}
                  </p>
                </div>

                {!reflectionSaved ? (
                  <button
                    onClick={handleSaveReflection}
                    className="w-full py-2.5 px-4 rounded-xl bg-[#59C9C0] hover:bg-[#4EBEA4] text-[#0B1118] font-semibold text-xs transition flex items-center justify-center gap-2 shadow cursor-pointer"
                  >
                    <BookOpen className="w-3.5 h-3.5" />
                    <span>Save Reflection to Research Notes</span>
                  </button>
                ) : (
                  <div className="space-y-2">
                    <div className="p-2 rounded-lg bg-emerald-950/40 border border-emerald-700/40 text-emerald-300 text-xs flex items-center gap-2">
                      <CheckCircle2 className="w-4 h-4 text-emerald-400" />
                      <span>Reflection saved to your Lab Notes.</span>
                    </div>
                    <button
                      onClick={() => setCurrentStage(4)}
                      className="w-full py-2 px-3 rounded-xl bg-[#1E2D3A] hover:bg-[#243746] text-[#E9F0F3] text-xs font-semibold border border-[#202F3C] transition flex items-center justify-center gap-1.5 cursor-pointer"
                    >
                      <span>Explore Candidate Shortlist →</span>
                    </button>
                  </div>
                )}
              </div>
            )}
          </div>
        )}

        {/* STAGE 4: CANDIDATE EXPLORATION */}
        {currentStage === 4 && (
          <div className="space-y-3">
            <div className="p-3 rounded-xl bg-[#0B1118]/80 border border-[#202F3C] space-y-1.5">
              <div className="text-[10px] font-mono uppercase text-[#59C9C0] tracking-wider font-semibold">
                Post-Challenge Exploration
              </div>
              <h3 className="text-xs font-bold text-[#E9F0F3] leading-snug">
                Compare QSAR Pipeline Candidates
              </h3>
              <p className="text-[11px] text-[#90A4AF] leading-relaxed">
                Our team screens novel molecules against this TERT pocket using machine learning. Select two candidates to contrast their predictions in beginner-friendly terms.
              </p>
            </div>

            {/* Select Candidate A and B */}
            <div className="grid grid-cols-2 gap-2 text-xs">
              <div>
                <label className="text-[10px] font-mono text-[#90A4AF] block mb-1">Molecule 1:</label>
                <select
                  value={candidateAId}
                  onChange={(e) => setCandidateAId(e.target.value)}
                  className="w-full p-1.5 rounded-lg bg-[#0B1118] border border-[#202F3C] text-xs text-[#E9F0F3] font-mono cursor-pointer"
                >
                  {candidates.map((c) => (
                    <option key={c.id} value={c.id}>
                      {c.name}
                    </option>
                  ))}
                </select>
              </div>

              <div>
                <label className="text-[10px] font-mono text-[#90A4AF] block mb-1">Molecule 2:</label>
                <select
                  value={candidateBId}
                  onChange={(e) => setCandidateBId(e.target.value)}
                  className="w-full p-1.5 rounded-lg bg-[#0B1118] border border-[#202F3C] text-xs text-[#E9F0F3] font-mono cursor-pointer"
                >
                  {candidates.map((c) => (
                    <option key={c.id} value={c.id}>
                      {c.name}
                    </option>
                  ))}
                </select>
              </div>
            </div>

            {/* Side by side accessible card */}
            <div className="grid grid-cols-2 gap-2 text-[11px]">
              {/* Card A */}
              <div className="p-2.5 rounded-xl bg-[#0B1118] border border-[#202F3C] space-y-1.5">
                <div className="font-bold text-[#E9F0F3] truncate">{candidateA.name}</div>
                <div className="text-[10px] font-mono text-[#59C9C0]">
                  {candidateA.tag || 'Candidate'}
                </div>

                <div className="pt-1 border-t border-[#202F3C] space-y-1">
                  <div>
                    <span className="text-[#90A4AF] block text-[10px]">Predicted Potency:</span>
                    <strong className="text-[#E9F0F3]">
                      {candidateA.prediction?.predicted_pic50
                        ? `pIC50 ${candidateA.prediction.predicted_pic50.toFixed(2)}`
                        : 'Pending'}
                    </strong>
                  </div>

                  <div>
                    <span className="text-[#90A4AF] block text-[10px]">Measured Value:</span>
                    <span className={candidateA.prediction?.measured_pic50 ? 'text-[#E9A76A] font-semibold' : 'text-[#627783]'}>
                      {candidateA.prediction?.measured_pic50
                        ? `pIC50 ${candidateA.prediction.measured_pic50.toFixed(2)}`
                        : 'Awaiting wet-lab'}
                    </span>
                  </div>
                </div>
              </div>

              {/* Card B */}
              <div className="p-2.5 rounded-xl bg-[#0B1118] border border-[#202F3C] space-y-1.5">
                <div className="font-bold text-[#E9F0F3] truncate">{candidateB.name}</div>
                <div className="text-[10px] font-mono text-[#59C9C0]">
                  {candidateB.tag || 'Candidate'}
                </div>

                <div className="pt-1 border-t border-[#202F3C] space-y-1">
                  <div>
                    <span className="text-[#90A4AF] block text-[10px]">Predicted Potency:</span>
                    <strong className="text-[#E9F0F3]">
                      {candidateB.prediction?.predicted_pic50
                        ? `pIC50 ${candidateB.prediction.predicted_pic50.toFixed(2)}`
                        : 'Pending'}
                    </strong>
                  </div>

                  <div>
                    <span className="text-[#90A4AF] block text-[10px]">Measured Value:</span>
                    <span className={candidateB.prediction?.measured_pic50 ? 'text-[#E9A76A] font-semibold' : 'text-[#627783]'}>
                      {candidateB.prediction?.measured_pic50
                        ? `pIC50 ${candidateB.prediction.measured_pic50.toFixed(2)}`
                        : 'Awaiting wet-lab'}
                    </span>
                  </div>
                </div>
              </div>
            </div>

            {/* Plain English explanation */}
            <div className="p-2.5 rounded-xl bg-[#0B1118]/80 border border-[#202F3C] text-[10px] text-[#90A4AF] leading-relaxed space-y-1">
              <div>
                🔬 <strong className="text-[#E9F0F3]">Understanding Potency (pIC50):</strong> Higher numbers mean tighter binding. Each +1 increase represents a 10-fold stronger affinity.
              </div>
              <div>
                ⚖️ <strong className="text-[#E9F0F3]">Model Uncertainty:</strong> Computational QSAR predictions carry ~0.5 log units of standard error.
              </div>
              <div className="text-[#627783] pt-0.5">
                Note: No synthetic 3D docking poses are fabricated. 3D coordinates are only loaded when experimentally solved or computed by the docking backend.
              </div>
            </div>

            {onNavigateToTab && (
              <button
                onClick={() => onNavigateToTab('compare')}
                className="w-full py-2 px-3 rounded-xl bg-[#1E2D3A] hover:bg-[#243746] text-[#59C9C0] text-xs font-semibold border border-[#59C9C0]/30 transition flex items-center justify-center gap-1.5 cursor-pointer"
              >
                <span>Open Full Research Benchmark (Compare Tab)</span>
                <ArrowRight className="w-3.5 h-3.5" />
              </button>
            )}
          </div>
        )}
      </div>
    </div>
  );
};
