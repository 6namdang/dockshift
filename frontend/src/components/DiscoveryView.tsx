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
  BookOpen,
  FilePlus,
  Compass,
  Check,
  Crosshair
} from 'lucide-react';
import { DiscoveryCategory, DiscoveryPrompt, SelectedComponentType } from '../types/docking';

interface DiscoveryViewProps {
  prompts: DiscoveryPrompt[];
  onSelectComponent: (component: SelectedComponentType) => void;
  onFocusInhibitor: () => void;
  onNavigateToTab: (tab: any) => void;
  onAddNote: (category: 'Observation' | 'Question' | 'Hypothesis' | 'Next Experiment', content: string, title?: string) => void;
}

export const DiscoveryView: React.FC<DiscoveryViewProps> = ({
  prompts,
  onSelectComponent,
  onFocusInhibitor,
  onNavigateToTab,
  onAddNote
}) => {
  const [selectedCategory, setSelectedCategory] = useState<DiscoveryCategory>('SUPPORT');
  const [userThoughts, setUserThoughts] = useState<Record<string, string>>({});
  const [savedSuccess, setSavedSuccess] = useState<string | null>(null);

  const activePrompt = prompts.find((p) => p.category === selectedCategory) || prompts[0];

  const categoryMeta: Record<
    DiscoveryCategory,
    { label: string; icon: React.FC<{ className?: string }>; color: string; border: string; bg: string; subtitle: string }
  > = {
    SUPPORT: {
      label: 'SUPPORT',
      icon: ShieldCheck,
      color: 'text-[#63E6DE]',
      border: 'border-[#63E6DE]/40',
      bg: 'bg-teal-950/40',
      subtitle: 'Understand telomerase architecture & BIBR1532 mechanism.'
    },
    CHALLENGE: {
      label: 'CHALLENGE',
      icon: Flame,
      color: 'text-[#FF7D45]',
      border: 'border-[#FF7D45]/40',
      bg: 'bg-orange-950/40',
      subtitle: 'Question docking score assumptions in RNP complexes.'
    },
    SURPRISE: {
      label: 'SURPRISE',
      icon: Sparkles,
      color: 'text-[#A79BEE]',
      border: 'border-[#A79BEE]/40',
      bg: 'bg-violet-950/40',
      subtitle: 'Inquire into RNA template dynamics & dual-contact binders.'
    },
    SPACE: {
      label: 'SPACE',
      icon: Maximize,
      color: 'text-[#438DFF]',
      border: 'border-[#438DFF]/40',
      bg: 'bg-blue-950/40',
      subtitle: 'Independent visual observation of the 3D binding pocket.'
    }
  };

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

  const handleExploreIn3D = () => {
    if (activePrompt.category === 'SUPPORT') {
      onFocusInhibitor();
    } else if (activePrompt.category === 'CHALLENGE') {
      onSelectComponent('pocket');
    } else if (activePrompt.category === 'SURPRISE') {
      onSelectComponent('terc');
    } else {
      onSelectComponent('all');
    }
    onNavigateToTab('explore');
  };

  return (
    <div className="h-full flex flex-col bg-[#0C1423] text-[#F2F7FF] overflow-y-auto">
      {/* Header */}
      <div className="px-6 py-4 border-b border-[#1c2e4a] bg-[#0E1728]/80 flex flex-wrap items-center justify-between gap-4">
        <div>
          <div className="flex items-center gap-2">
            <Lightbulb className="w-5 h-5 text-[#A79BEE]" />
            <h1 className="text-lg font-semibold tracking-tight text-[#F2F7FF]">
              Discovery Mode — What If?
            </h1>
            <span className="px-2 py-0.5 text-xs font-mono rounded bg-[#1c2e4a] text-[#A79BEE] border border-[#A79BEE]/20">
              Telomerase Inquiry Modes
            </span>
          </div>
          <p className="text-xs text-[#91A6BE] mt-0.5">
            Four scientific inquiry modes to stimulate hypotheses around human telomerase and allosteric small-molecule inhibition.
          </p>
        </div>

        <div className="text-[11px] font-mono text-[#5E7594] px-3 py-1.5 rounded-lg bg-[#152237] border border-[#1e3250]">
          Exploration Prompts • Not Scientific Conclusions
        </div>
      </div>

      <div className="p-6 max-w-6xl mx-auto w-full space-y-6">
        {/* Four Mode Selector Bar */}
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          {(['SUPPORT', 'CHALLENGE', 'SURPRISE', 'SPACE'] as DiscoveryCategory[]).map((cat) => {
            const meta = categoryMeta[cat];
            const Icon = meta.icon;
            const isSelected = selectedCategory === cat;
            return (
              <button
                key={cat}
                onClick={() => setSelectedCategory(cat)}
                className={`p-3.5 rounded-xl border text-left transition-all relative overflow-hidden ${
                  isSelected
                    ? `${meta.bg} ${meta.border} shadow-lg glow-blue`
                    : 'bg-[#152237]/60 border-[#1e3250] hover:border-[#1c2e4a]'
                }`}
              >
                <div className="flex items-center justify-between mb-1.5">
                  <div className={`font-mono text-xs font-bold ${meta.color} flex items-center gap-1.5`}>
                    <Icon className="w-4 h-4" />
                    <span>{meta.label}</span>
                  </div>
                  {isSelected && (
                    <span className="w-1.5 h-1.5 rounded-full bg-[#63E6DE] animate-ping" />
                  )}
                </div>
                <div className="text-[11px] text-[#91A6BE] line-clamp-2 leading-tight">
                  {meta.subtitle}
                </div>
              </button>
            );
          })}
        </div>

        {/* Active Mode Deep Dive Card */}
        <div className="p-6 rounded-2xl bg-[#152237] border border-[#1e3250] shadow-xl space-y-6">
          <div className="flex flex-wrap items-center justify-between pb-4 border-b border-[#1c2e4a] gap-3">
            <div className="space-y-1">
              <div className="flex items-center gap-2">
                <span
                  className={`px-2.5 py-0.5 text-xs font-mono font-bold rounded ${categoryMeta[selectedCategory].bg} ${categoryMeta[selectedCategory].color} border ${categoryMeta[selectedCategory].border}`}
                >
                  {selectedCategory}
                </span>
                <span className="text-xs font-mono text-[#5E7594]">Discovery Mode</span>
              </div>
              <h2 className="text-xl font-bold text-[#F2F7FF]">
                {activePrompt.question}
              </h2>
            </div>

            <button
              onClick={handleExploreIn3D}
              className="px-3.5 py-2 text-xs font-mono rounded-lg bg-[#1c2e4a] hover:bg-[#253d63] text-[#63E6DE] border border-[#63E6DE]/30 transition flex items-center gap-2 shadow-sm"
            >
              <Compass className="w-4 h-4" />
              <span>Inspect in 3D Viewer</span>
            </button>
          </div>

          {/* Biological Background / Context */}
          <div className="space-y-2">
            <h3 className="text-xs font-mono uppercase tracking-wider text-[#91A6BE]">
              Biological Context &amp; Evidence (PDB 9Q14)
            </h3>
            <div className="p-4 rounded-xl bg-[#0C1423] border border-[#1e3250] text-xs text-[#91A6BE] leading-relaxed">
              {activePrompt.context}
            </div>
          </div>

          {/* Critical Reflection Trigger */}
          <div className="p-4 rounded-xl bg-[#0C1423]/70 border border-[#1e3250] space-y-2">
            <div className="flex items-center gap-2 text-xs font-mono text-[#FF7D45] font-semibold">
              <Lightbulb className="w-4 h-4" />
              <span>Critical Reflection Trigger:</span>
            </div>
            <p className="text-sm text-[#F2F7FF] font-medium italic leading-relaxed">
              &ldquo;{activePrompt.reflectionQuestion}&rdquo;
            </p>
          </div>

          {/* Interactive Thought Space */}
          <div className="space-y-2">
            <div className="flex items-center justify-between">
              <label className="text-xs font-mono uppercase tracking-wider text-[#91A6BE]">
                Researcher Thought Space (Optional Reflection)
              </label>
              <span className="text-[10px] font-mono text-[#5E7594]">
                Recorded directly to lab notebook
              </span>
            </div>
            <textarea
              rows={3}
              value={userThoughts[activePrompt.id] || ''}
              onChange={(e) =>
                setUserThoughts({ ...userThoughts, [activePrompt.id]: e.target.value })
              }
              placeholder={`Write your reflections or experimental ideas regarding ${selectedCategory.toLowerCase()}...`}
              className="w-full p-3 rounded-xl bg-[#0C1423] border border-[#1e3250] text-xs text-[#F2F7FF] placeholder-[#5E7594] outline-none focus:border-[#63E6DE] transition resize-none font-sans"
            />
          </div>

          {/* Suggested Synthesis Note */}
          <div className="p-3.5 rounded-xl bg-[#121c2e] border border-[#1c2e4a] text-xs space-y-1">
            <span className="text-[10px] font-mono uppercase tracking-wider text-[#63E6DE] block">
              Default Synthesis Note:
            </span>
            <p className="text-[#91A6BE] leading-relaxed text-[11px] font-mono">
              {activePrompt.suggestedNote}
            </p>
          </div>

          {/* Bottom Actions */}
          <div className="flex flex-wrap items-center justify-between pt-2 gap-3">
            <div className="text-[11px] text-[#5E7594] font-mono flex items-center gap-1.5">
              <span className="w-2 h-2 rounded-full bg-[#FF7D45]" />
              Structured inquiry sparks deeper domain hypotheses before running heavy compute jobs.
            </div>

            <div className="flex items-center gap-3">
              <button
                onClick={handleSaveToNotes}
                className={`px-4 py-2 text-xs font-mono font-medium rounded-lg transition flex items-center gap-2 ${
                  savedSuccess === activePrompt.id
                    ? 'bg-emerald-600 text-white'
                    : 'bg-[#63E6DE] hover:bg-[#52c9c1] text-[#0C1423]'
                }`}
              >
                {savedSuccess === activePrompt.id ? (
                  <>
                    <Check className="w-4 h-4" />
                    <span>Saved to Research Notes!</span>
                  </>
                ) : (
                  <>
                    <FilePlus className="w-4 h-4" />
                    <span>Add to Research Notes</span>
                  </>
                )}
              </button>

              <button
                onClick={() => onNavigateToTab('notes')}
                className="px-3 py-2 text-xs font-mono rounded-lg bg-[#1c2e4a] hover:bg-[#253d63] text-[#F2F7FF] border border-[#1e3250] transition flex items-center gap-1.5"
              >
                <BookOpen className="w-3.5 h-3.5" />
                <span>Go to Notes</span>
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};
