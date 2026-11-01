/**
 * @license
 * SPDX-License-Identifier: Apache-2.0
 */

import React, { useState } from 'react';
import {
  Lightbulb,
  ShieldCheck,
  Flame,
  Sparkles,
  Maximize,
  Compass,
  Check,
  FilePlus,
  BookOpen,
  ArrowRight,
  Info,
  HelpCircle,
  Award,
  Zap,
  Layers,
  ChevronDown,
  ChevronUp
} from 'lucide-react';
import { DiscoveryCategory, DiscoveryPrompt, GuidedChallenge, SelectedComponentType } from '../types/docking';

interface DiscoverViewProps {
  challenges: GuidedChallenge[];
  prompts: DiscoveryPrompt[];
  onSelectComponent: (component: SelectedComponentType) => void;
  onFocusInhibitor: () => void;
  onNavigateToTab: (tab: any) => void;
  onAddNote: (category: 'Observation' | 'Question' | 'Hypothesis' | 'Next Experiment', content: string, title?: string) => void;
}

export const DiscoverView: React.FC<DiscoverViewProps> = ({
  challenges,
  prompts,
  onSelectComponent,
  onFocusInhibitor,
  onNavigateToTab,
  onAddNote
}) => {
  const [level, setLevel] = useState<'beginner' | 'advanced'>('beginner');
  const [expandedChallenge, setExpandedChallenge] = useState<string>(challenges[0]?.id || 'challenge-allosteric');
  const [activeCategory, setActiveCategory] = useState<DiscoveryCategory>('SUPPORT');
  const [userThoughts, setUserThoughts] = useState<Record<string, string>>({});
  const [savedSuccess, setSavedSuccess] = useState<string | null>(null);

  const activePrompt = prompts.find((p) => p.category === activeCategory) || prompts[0];

  const handleSaveToNotes = () => {
    const customThought = userThoughts[activePrompt.id] || '';
    const noteContent = customThought
      ? `${activePrompt.suggestedNote}\n\nResearcher Reflection:\n${customThought}`
      : activePrompt.suggestedNote;

    const noteCategory =
      activePrompt.category === 'SUPPORT'
        ? 'Observation'
        : activePrompt.category === 'CHALLENGE'
        ? 'Hypothesis'
        : activePrompt.category === 'SURPRISE'
        ? 'Question'
        : 'Observation';

    onAddNote(noteCategory, noteContent, `[Discovery ${activePrompt.category}] ${activePrompt.title}`);
    setSavedSuccess(activePrompt.id);
    setTimeout(() => setSavedSuccess(null), 3000);
  };

  const handleChallengeAction = (ch: GuidedChallenge) => {
    if (ch.focusTarget === 'inhibitor') {
      onFocusInhibitor();
    } else {
      onSelectComponent(ch.focusTarget);
    }
    onNavigateToTab('playground');
  };

  return (
    <div className="h-full flex flex-col bg-[#0B1118] text-[#E9F0F3] overflow-y-auto select-none">
      {/* Header */}
      <div className="px-6 py-4 border-b border-[#202F3C] bg-[#0B1118]/90 flex flex-wrap items-center justify-between gap-4">
        <div>
          <div className="flex items-center gap-2">
            <Lightbulb className="w-5 h-5 text-[#59C9C0]" />
            <h1 className="text-lg font-bold tracking-tight text-[#E9F0F3]">
              Discover Telomerase Biology
            </h1>
            <span className="px-2 py-0.5 text-xs font-mono rounded bg-[#18232D] text-[#59C9C0] border border-[#59C9C0]/20">
              Beginner-Friendly Introduction
            </span>
          </div>
          <p className="text-xs text-[#90A4AF] mt-0.5">
            Understand how human telomerase extends chromosome ends and why it is a premier oncology drug target.
          </p>
        </div>

        {/* Level toggle */}
        <div className="flex bg-[#18232D] p-1 rounded-xl border border-[#202F3C] text-xs font-mono">
          <button
            onClick={() => setLevel('beginner')}
            className={`px-3 py-1 rounded-lg transition cursor-pointer ${
              level === 'beginner'
                ? 'bg-[#202F3C] text-[#59C9C0] font-semibold'
                : 'text-[#90A4AF] hover:text-[#E9F0F3]'
            }`}
          >
            Beginner Mode
          </button>
          <button
            onClick={() => setLevel('advanced')}
            className={`px-3 py-1 rounded-lg transition cursor-pointer ${
              level === 'advanced'
                ? 'bg-[#202F3C] text-[#A79BEE] font-semibold'
                : 'text-[#90A4AF] hover:text-[#E9F0F3]'
            }`}
          >
            Advanced Scientific
          </button>
        </div>
      </div>

      <div className="p-6 max-w-5xl mx-auto w-full space-y-6">
        {/* Featured Interactive Challenge Banner */}
        <div className="p-5 rounded-2xl bg-gradient-to-r from-[#18232D] to-[#1E2D3A] border border-[#59C9C0]/30 shadow-lg flex flex-wrap items-center justify-between gap-4">
          <div className="space-y-1">
            <div className="flex items-center gap-2">
              <span className="text-base">🎮</span>
              <span className="text-xs font-mono font-bold uppercase tracking-wider text-[#59C9C0]">
                Playground Challenge 01
              </span>
              <span className="text-[10px] font-mono px-2 py-0.2 rounded bg-[#59C9C0]/20 text-[#59C9C0]">
                Interactive
              </span>
            </div>
            <h2 className="text-base font-bold text-[#E9F0F3]">
              Find the Inhibitor: Can you locate BIBR1532 on human telomerase?
            </h2>
            <p className="text-xs text-[#90A4AF] max-w-xl">
              Rotate and zoom the experimental 3.0 Å cryo-EM structure, hunt for the bound small molecule, and reflect on drug discovery requirements.
            </p>
          </div>

          <button
            onClick={() => {
              onFocusInhibitor();
              onNavigateToTab('playground');
            }}
            className="px-4 py-2.5 rounded-xl bg-[#59C9C0] hover:bg-[#4EBEA4] text-[#0B1118] font-bold text-xs transition flex items-center gap-2 shadow-md cursor-pointer active:scale-95"
          >
            <Sparkles className="w-4 h-4" />
            <span>Launch Challenge in 3D Playground</span>
          </button>
        </div>

        {/* Beginner Introduction Card */}
        <section className="p-5 rounded-2xl bg-[#18232D] border border-[#202F3C] shadow-md space-y-4">
          <div className="flex items-center gap-2.5">
            <div className="w-8 h-8 rounded-xl bg-[#0B1118] border border-[#202F3C] flex items-center justify-center text-[#59C9C0]">
              <Sparkles className="w-4 h-4" />
            </div>
            <div>
              <h2 className="text-base font-bold text-[#E9F0F3]">
                What is Telomerase? The Cellular Immortality Enzyme
              </h2>
              <span className="text-[11px] font-mono text-[#90A4AF]">
                Key concept for aspiring drug discovery scientists
              </span>
            </div>
          </div>

          <div className="space-y-3 text-xs text-[#90A4AF] leading-relaxed">
            <p>
              Every time a normal human cell divides, its DNA duplication machinery cannot completely copy the very ends of chromosomes
              (the <strong className="text-[#E9F0F3]">&ldquo;end-replication problem&rdquo;</strong>). Over time, telomeres shorten like the burning fuse of a firework.
              When telomeres get too short, cells stop dividing and die (senescence).
            </p>
            <div className="p-3.5 rounded-xl bg-[#0B1118] border border-[#202F3C] grid grid-cols-1 md:grid-cols-3 gap-3 font-mono text-[11px]">
              <div className="space-y-1">
                <span className="text-[#59C9C0] font-bold block">1. TERT Subunit (Cyan)</span>
                <p className="text-[#90A4AF]">The protein engine that synthesizes DNA repeats using reverse transcription.</p>
              </div>
              <div className="space-y-1">
                <span className="text-[#A79BEE] font-bold block">2. TERC RNA (Violet)</span>
                <p className="text-[#90A4AF]">An internal RNA strip that provides the master template code (3&apos;-CAAUCCCAAUC-5&apos;).</p>
              </div>
              <div className="space-y-1">
                <span className="text-[#FF7D45] font-bold block">3. BIBR1532 (Orange)</span>
                <p className="text-[#90A4AF]">A small-molecule drug that wedges into TERT to stop repeat synthesis.</p>
              </div>
            </div>
          </div>
        </section>

        {/* Guided Interactive Challenges */}
        <section className="space-y-3">
          <div className="flex items-center justify-between">
            <h2 className="text-sm font-bold text-[#F2F7FF] flex items-center gap-2">
              <Award className="w-4 h-4 text-[#FF7D45]" />
              Guided Exploration Challenges (PDB 9Q14)
            </h2>
            <span className="text-[11px] font-mono text-[#5E7594]">
              Hands-on molecular learning
            </span>
          </div>

          <div className="space-y-2.5">
            {challenges.map((ch) => {
              const isOpen = expandedChallenge === ch.id;
              return (
                <div
                  key={ch.id}
                  className="rounded-2xl bg-[#18232D] border border-[#202F3C] overflow-hidden transition"
                >
                  <button
                    onClick={() => setExpandedChallenge(isOpen ? '' : ch.id)}
                    className="w-full p-4 flex items-center justify-between text-left hover:bg-[#202F3C]/50 transition cursor-pointer"
                  >
                    <div className="flex items-center gap-3">
                      <span className="w-6 h-6 rounded-full bg-[#0B1118] text-[#59C9C0] font-bold text-xs flex items-center justify-center font-mono border border-[#59C9C0]/30">
                        ?
                      </span>
                      <div>
                        <div className="font-bold text-sm text-[#E9F0F3]">
                          {ch.title}
                        </div>
                        <div className="text-[11px] text-[#90A4AF]">
                          {ch.question}
                        </div>
                      </div>
                    </div>
                    <div className="flex items-center gap-2 text-xs font-mono text-[#90A4AF]">
                      <span className="px-2 py-0.5 rounded bg-[#0B1118] text-[#59C9C0] border border-[#202F3C]">
                        {ch.level}
                      </span>
                      {isOpen ? <ChevronUp className="w-4 h-4" /> : <ChevronDown className="w-4 h-4" />}
                    </div>
                  </button>

                  {isOpen && (
                    <div className="p-4 pt-1 border-t border-[#202F3C] bg-[#0B1118]/60 space-y-3 text-xs leading-relaxed">
                      <div className="p-2.5 rounded-lg bg-[#18232D] border border-[#202F3C] text-[#90A4AF]">
                        <strong className="text-[#FF7D45] block text-[11px] mb-0.5">Hint:</strong>
                        {ch.hint}
                      </div>

                      <div className="text-[#E9F0F3]">
                        <strong className="text-[#59C9C0] block text-[11px] mb-0.5">Explanation:</strong>
                        {ch.explanation}
                      </div>

                      <div className="pt-2 flex justify-end">
                        <button
                          onClick={() => handleChallengeAction(ch)}
                          className="px-3.5 py-1.5 rounded-lg bg-[#59C9C0] hover:bg-[#4EBEA4] text-[#0B1118] font-mono text-xs font-bold transition flex items-center gap-1.5 shadow-sm cursor-pointer"
                        >
                          <Compass className="w-3.5 h-3.5" />
                          <span>{ch.actionLabel}</span>
                        </button>
                      </div>
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        </section>

        {/* Four Scientific Inquiry Modes (What If?) */}
        <section className="p-5 rounded-2xl bg-[#18232D] border border-[#202F3C] shadow-md space-y-4">
          <div className="flex items-center justify-between pb-2 border-b border-[#202F3C]">
            <div>
              <h2 className="text-sm font-bold text-[#E9F0F3]">
                Discovery Mode — What If? Postures
              </h2>
              <p className="text-xs text-[#90A4AF]">
                Four critical thinking frameworks for evaluating telomerase molecular data.
              </p>
            </div>
            <div className="flex gap-1.5">
              {(['SUPPORT', 'CHALLENGE', 'SURPRISE', 'SPACE'] as DiscoveryCategory[]).map((cat) => (
                <button
                  key={cat}
                  onClick={() => setActiveCategory(cat)}
                  className={`px-2.5 py-1 rounded-lg text-xs font-mono font-bold transition ${
                    activeCategory === cat
                      ? 'bg-[#1c2e4a] text-[#63E6DE] border border-[#63E6DE]/40'
                      : 'text-[#91A6BE] hover:text-[#F2F7FF]'
                  }`}
                >
                  {cat}
                </button>
              ))}
            </div>
          </div>

          <div className="p-4 rounded-xl bg-[#0C1423] border border-[#1e3250] space-y-3 text-xs">
            <div className="font-bold text-sm text-[#F2F7FF]">
              {activePrompt.question}
            </div>
            <p className="text-[#91A6BE] leading-relaxed">
              {activePrompt.context}
            </p>
            <div className="p-3 rounded-lg bg-[#152237] border border-[#1e3250] text-[#FF7D45] italic">
              &ldquo;{activePrompt.reflectionQuestion}&rdquo;
            </div>

            <div className="pt-2 flex items-center justify-between">
              <span className="text-[11px] font-mono text-[#5E7594]">
                Inquiry Trigger
              </span>
              <button
                onClick={handleSaveToNotes}
                className="px-3 py-1.5 rounded-lg bg-[#1c2e4a] hover:bg-[#253d63] text-[#63E6DE] font-mono text-xs font-semibold border border-[#63E6DE]/30 transition flex items-center gap-1.5"
              >
                {savedSuccess === activePrompt.id ? (
                  <>
                    <Check className="w-3.5 h-3.5" />
                    <span>Saved to Notes</span>
                  </>
                ) : (
                  <>
                    <FilePlus className="w-3.5 h-3.5" />
                    <span>Save to Research Notes</span>
                  </>
                )}
              </button>
            </div>
          </div>
        </section>
      </div>
    </div>
  );
};
