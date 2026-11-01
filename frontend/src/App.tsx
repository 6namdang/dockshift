/**
 * @license
 * SPDX-License-Identifier: Apache-2.0
 */

import React, { useState, useEffect } from 'react';
import { NavigationSidebar, NavigationTab } from './components/NavigationSidebar';
import { DiscoverView } from './components/DiscoverView';
import { ScreenView } from './components/ScreenView';
import { MolecularViewer } from './components/MolecularViewer';
import { MolecularInspector } from './components/MolecularInspector';
import { CompareView } from './components/CompareView';
import { AgentRunsView } from './components/AgentRunsView';
import { LiteratureView } from './components/LiteratureView';
import { ResearchNotesView } from './components/ResearchNotesView';
import {
  dockingService,
  TARGET_TELOMERASE_9Q14,
  SHORTLISTED_CANDIDATES,
  INITIAL_DOCKING_RESULTS,
  DISCOVERY_PROMPTS,
  GUIDED_CHALLENGES,
  INITIAL_RESEARCH_NOTES
} from './services/dockingService';
import {
  Protein,
  Ligand,
  DockingResult,
  DiscoveryPrompt,
  GuidedChallenge,
  ResearchNote,
  ComponentVisibility,
  SelectedComponentType
} from './types/docking';
import { X, BookOpen } from 'lucide-react';

export default function App() {
  const [activeTab, setActiveTab] = useState<NavigationTab>('playground');
  const [protein, setProtein] = useState<Protein>(TARGET_TELOMERASE_9Q14);
  const [candidates, setCandidates] = useState<Ligand[]>(SHORTLISTED_CANDIDATES);
  const [selectedCandidateId, setSelectedCandidateId] = useState<string>('bibr1532');
  const [dockingResults, setDockingResults] = useState<Record<string, DockingResult>>(INITIAL_DOCKING_RESULTS);
  const [discoveryPrompts, setDiscoveryPrompts] = useState<DiscoveryPrompt[]>(DISCOVERY_PROMPTS);
  const [challenges, setChallenges] = useState<GuidedChallenge[]>(GUIDED_CHALLENGES);
  const [notes, setNotes] = useState<ResearchNote[]>(INITIAL_RESEARCH_NOTES);
  const [isNotesOpen, setIsNotesOpen] = useState<boolean>(false);
  const [isLoadingScreening, setIsLoadingScreening] = useState<boolean>(false);
  const [screeningSource, setScreeningSource] = useState<'backend' | 'demo'>('demo');

  // 3D Viewport Controls & Selections
  const [selectedComponent, setSelectedComponent] = useState<SelectedComponentType>('all');
  const [visibility, setVisibility] = useState<ComponentVisibility>({
    showProtein: true,
    showRna: true,
    showDna: true,
    showInhibitor: true
  });
  const [focusedResidue, setFocusedResidue] = useState<{ resi: number; chain: string } | null>(null);

  // Initialize data from centralized service
  useEffect(() => {
    const initData = async () => {
      const tgt = await dockingService.getTargetProtein();
      const cands = await dockingService.getCandidates();
      const docks = await dockingService.getAllDockingResults();
      const prompts = dockingService.getDiscoveryPrompts();
      const chs = dockingService.getGuidedChallenges();
      const initialNotes = dockingService.getNotes();

      setProtein(tgt);
      setCandidates(cands);
      setDockingResults(docks);
      setDiscoveryPrompts(prompts);
      setChallenges(chs);
      setNotes(initialNotes);
    };

    initData();

    const unsubscribe = dockingService.subscribe(() => {
      setNotes(dockingService.getNotes());
    });

    return () => unsubscribe();
  }, []);

  // Global keyboard shortcuts for navigation and Research Notes overlay
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      // 1. Toggle Research Notes overlay: Ctrl+Shift+N or Cmd+Shift+N
      if ((e.ctrlKey || e.metaKey) && e.shiftKey && (e.key === 'N' || e.key === 'n')) {
        e.preventDefault();
        setIsNotesOpen((prev) => !prev);
        return;
      }

      // 2. Close overlay if open: Escape
      if (e.key === 'Escape' && isNotesOpen) {
        e.preventDefault();
        setIsNotesOpen(false);
        return;
      }

      // Avoid capturing single-key numbers when typing inside interactive elements
      const activeElem = document.activeElement;
      const isInputActive =
        activeElem &&
        (activeElem.tagName === 'INPUT' ||
          activeElem.tagName === 'TEXTAREA' ||
          activeElem.tagName === 'SELECT' ||
          (activeElem as HTMLElement).isContentEditable);

      if (isInputActive) {
        return;
      }

      // 3. Tab navigation shortcuts 1-5 without modifiers
      if (!e.ctrlKey && !e.altKey && !e.metaKey && !e.shiftKey) {
        switch (e.key) {
          case '1':
            e.preventDefault();
            setActiveTab('discover');
            setFocusedResidue(null);
            break;
          case '2':
            e.preventDefault();
            setActiveTab('screen');
            setFocusedResidue(null);
            break;
          case '3':
            e.preventDefault();
            setActiveTab('playground');
            break;
          case '4':
            e.preventDefault();
            setActiveTab('compare');
            setFocusedResidue(null);
            break;
          case '6':
            e.preventDefault();
            setActiveTab('agents');
            setFocusedResidue(null);
            break;
          case '5':
            e.preventDefault();
            setActiveTab('literature');
            setFocusedResidue(null);
            break;
        }
      }
    };

    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [isNotesOpen]);

  const handleToggleVisibility = (key: keyof ComponentVisibility) => {
    setVisibility((prev) => ({
      ...prev,
      [key]: !prev[key]
    }));
  };

  const handleFocusInhibitor = () => {
    setSelectedComponent('inhibitor');
    if (!visibility.showInhibitor) {
      setVisibility((prev) => ({ ...prev, showInhibitor: true }));
    }
  };

  const handleRunScreening = async (count: number) => {
    setIsLoadingScreening(true);
    try {
      const res = await dockingService.fetchScreeningShortlist(count);
      setCandidates(res.entries);
      setScreeningSource(res.source);
      if (res.entries.length > 0) {
        setSelectedCandidateId(res.entries[0].id);
      }
    } finally {
      setIsLoadingScreening(false);
    }
  };

  const handleExploreInPlayground = (candidateId: string) => {
    setSelectedCandidateId(candidateId);
    setActiveTab('playground');
    // If exploring BIBR1532, focus inhibitor
    if (candidateId === 'bibr1532') {
      handleFocusInhibitor();
    }
  };

  const handleAddNote = (
    category: 'Observation' | 'Question' | 'Hypothesis' | 'Next Experiment',
    content: string,
    title?: string
  ) => {
    const newNote = dockingService.addNote({
      title: title || `Observation: ${protein.name}`,
      category,
      content,
      targetId: protein.id,
      candidateId: selectedCandidateId,
      tags: [protein.pdbId, 'Telomerase', 'BIBR1532']
    });
    setNotes(dockingService.getNotes());
    return newNote;
  };

  const handleAddNoteForCandidate = (candidateId: string) => {
    const candidate = candidates.find((c) => c.id === candidateId);
    if (!candidate) return;
    handleAddNote(
      'Observation',
      `Inspected candidate ${candidate.name} targeting ${candidate.targetSite}. QSAR predicted pIC50: ${candidate.prediction?.predicted_pic50.toFixed(2) || '—'}. Awaiting 3D docking pipeline execution.`,
      `Pipeline Record: ${candidate.name}`
    );
    setIsNotesOpen(true);
  };

  const handleUpdateNote = (id: string, updates: Partial<Omit<ResearchNote, 'id'>>) => {
    dockingService.updateNote(id, updates);
    setNotes(dockingService.getNotes());
  };

  const handleDeleteNote = (id: string) => {
    dockingService.deleteNote(id);
    setNotes(dockingService.getNotes());
  };

  return (
    <div className="flex h-screen w-screen bg-[#0B1118] text-[#E9F0F3] overflow-hidden font-sans select-none">
      {/* 1. Left Sidebar: 5-Stage Navigation Workflow */}
      <NavigationSidebar
        activeTab={activeTab}
        onSelectTab={(tab) => {
          setActiveTab(tab);
          setFocusedResidue(null);
        }}
        noteCount={notes.length}
        onOpenNotes={() => setIsNotesOpen(true)}
      />

      {/* 2. Main Center Workspace */}
      <main className="flex-1 flex overflow-hidden relative">
        {/* 1. DISCOVER TAB */}
        {activeTab === 'discover' && (
          <div className="flex-1 h-full">
            <DiscoverView
              challenges={challenges}
              prompts={discoveryPrompts}
              onSelectComponent={setSelectedComponent}
              onFocusInhibitor={handleFocusInhibitor}
              onNavigateToTab={(tab) => setActiveTab(tab)}
              onAddNote={handleAddNote}
            />
          </div>
        )}

        {/* 2. SCREEN TAB */}
        {activeTab === 'screen' && (
          <div className="flex-1 h-full">
            <ScreenView
              protein={protein}
              candidates={candidates}
              selectedCandidateId={selectedCandidateId}
              onSelectCandidate={setSelectedCandidateId}
              onExploreInPlayground={handleExploreInPlayground}
              onRunScreening={handleRunScreening}
              isLoadingScreening={isLoadingScreening}
              source={screeningSource}
            />
          </div>
        )}

        {/* 3. MOLECULAR PLAYGROUND TAB (Visual Centerpiece) */}
        {activeTab === 'playground' && (
          <div className="flex-1 flex h-full overflow-hidden">
            <div className="flex-1 h-full">
              <MolecularViewer
                protein={protein}
                selectedComponent={selectedComponent}
                onSelectComponent={setSelectedComponent}
                visibility={visibility}
                onToggleVisibility={handleToggleVisibility}
                focusedResidue={focusedResidue}
                candidates={candidates}
                selectedCandidateId={selectedCandidateId}
                onSelectCandidate={(id) => {
                  setSelectedCandidateId(id);
                  if (id === 'bibr1532') {
                    handleFocusInhibitor();
                  }
                }}
                dockingResults={dockingResults}
                onAddNote={handleAddNote}
                onNavigateToTab={(tab) => setActiveTab(tab as any)}
              />
            </div>

            {/* Right Sidebar: Molecular Inspector */}
            <MolecularInspector
              protein={protein}
              selectedComponent={selectedComponent}
              onSelectComponent={setSelectedComponent}
              visibility={visibility}
              onToggleVisibility={handleToggleVisibility}
              onFocusInhibitor={handleFocusInhibitor}
              candidates={candidates}
              selectedCandidateId={selectedCandidateId}
              onSelectCandidate={setSelectedCandidateId}
              dockingResults={dockingResults}
              onNavigateToCompare={() => setActiveTab('compare')}
              onAddNoteForCandidate={handleAddNoteForCandidate}
            />
          </div>
        )}

        {/* 4. COMPARE TAB */}
        {activeTab === 'compare' && (
          <div className="flex-1 h-full">
            <CompareView
              protein={protein}
              candidates={candidates}
              dockingResults={dockingResults}
              notes={notes}
              onAddNoteForCandidate={handleAddNoteForCandidate}
              onNavigateToTab={(tab) => setActiveTab(tab)}
              onExploreInPlayground={handleExploreInPlayground}
            />
          </div>
        )}

        {/* 5. LITERATURE TAB */}
        {activeTab === 'agents' && <AgentRunsView candidate={candidates.find(c => c.id === selectedCandidateId)} />}

        {activeTab === 'literature' && (
          <div className="flex-1 h-full">
            <LiteratureView />
          </div>
        )}
      </main>

      {/* Accessible Slide-over / Modal for Research Notes */}
      {isNotesOpen && (
        <div
          className="fixed inset-0 z-50 bg-[#0C1423]/80 backdrop-blur-sm flex justify-end cursor-pointer"
          onClick={() => setIsNotesOpen(false)}
        >
          <div
            className="w-full max-w-2xl h-full bg-[#0C1423] border-l border-[#1c2e4a] shadow-2xl flex flex-col animate-slideLeft cursor-default"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="p-4 border-b border-[#1c2e4a] bg-[#121c2e] flex items-center justify-between">
              <div className="flex items-center gap-2">
                <BookOpen className="w-4 h-4 text-[#63E6DE]" />
                <h2 className="text-sm font-bold text-[#F2F7FF]">
                  Research Notes &amp; Lab Notebook
                </h2>
                <kbd className="text-[10px] font-mono px-1.5 py-0.5 rounded bg-[#152237] text-[#5E7594] border border-[#1e3250]">
                  Esc to close
                </kbd>
              </div>
              <button
                onClick={() => setIsNotesOpen(false)}
                className="p-1 rounded-lg text-[#91A6BE] hover:text-[#F2F7FF] hover:bg-[#152237] transition"
              >
                <X className="w-5 h-5" />
              </button>
            </div>

            <div className="flex-1 overflow-hidden">
              <ResearchNotesView
                protein={protein}
                notes={notes}
                onAddNote={handleAddNote}
                onUpdateNote={handleUpdateNote}
                onDeleteNote={handleDeleteNote}
              />
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
