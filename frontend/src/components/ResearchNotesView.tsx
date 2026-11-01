/**
 * @license
 * SPDX-License-Identifier: Apache-2.0
 */

import React, { useState } from 'react';
import {
  BookOpen,
  Plus,
  Search,
  Filter,
  Download,
  Trash2,
  Edit3,
  Calendar,
  Tag,
  FileText,
  Check,
  X,
  Sparkles,
  Shield
} from 'lucide-react';
import { ResearchNote, Protein } from '../types/docking';

interface ResearchNotesViewProps {
  protein: Protein;
  notes: ResearchNote[];
  onAddNote: (category: 'Observation' | 'Question' | 'Hypothesis' | 'Next Experiment', content: string, title?: string) => void;
  onUpdateNote: (id: string, updates: Partial<Omit<ResearchNote, 'id'>>) => void;
  onDeleteNote: (id: string) => void;
}

export const ResearchNotesView: React.FC<ResearchNotesViewProps> = ({
  protein,
  notes,
  onAddNote,
  onUpdateNote,
  onDeleteNote
}) => {
  const [searchQuery, setSearchQuery] = useState('');
  const [selectedCategory, setSelectedCategory] = useState<string>('ALL');
  const [isAdding, setIsAdding] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);

  // New Note Form state
  const [newTitle, setNewTitle] = useState('');
  const [newCategory, setNewCategory] = useState<'Observation' | 'Question' | 'Hypothesis' | 'Next Experiment'>('Observation');
  const [newContent, setNewContent] = useState('');

  // Edit Note Form state
  const [editTitle, setEditTitle] = useState('');
  const [editCategory, setEditCategory] = useState<'Observation' | 'Question' | 'Hypothesis' | 'Next Experiment'>('Observation');
  const [editContent, setEditContent] = useState('');

  const filteredNotes = notes.filter((n) => {
    const matchesSearch =
      n.title.toLowerCase().includes(searchQuery.toLowerCase()) ||
      n.content.toLowerCase().includes(searchQuery.toLowerCase()) ||
      n.tags.some((t) => t.toLowerCase().includes(searchQuery.toLowerCase()));
    const matchesCat = selectedCategory === 'ALL' || n.category === selectedCategory;
    return matchesSearch && matchesCat;
  });

  const handleCreateSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!newTitle.trim() || !newContent.trim()) return;
    onAddNote(newCategory, newContent, newTitle);
    setNewTitle('');
    setNewContent('');
    setIsAdding(false);
  };

  const startEdit = (note: ResearchNote) => {
    setEditingId(note.id);
    setEditTitle(note.title);
    setEditCategory(note.category);
    setEditContent(note.content);
  };

  const handleEditSubmit = (id: string) => {
    if (!editTitle.trim() || !editContent.trim()) return;
    onUpdateNote(id, {
      title: editTitle,
      category: editCategory,
      content: editContent
    });
    setEditingId(null);
  };

  const exportNotesAsMarkdown = () => {
    let md = `# DockShift Research Notes — ${protein.name} (${protein.pdbId})\n\n`;
    md += `*Exported on ${new Date().toLocaleString()}*\n\n---\n\n`;
    notes.forEach((note) => {
      md += `### [${note.category}] ${note.title}\n`;
      md += `**Date:** ${note.timestamp} | **Tags:** ${note.tags.join(', ')}\n\n`;
      md += `${note.content}\n\n---\n\n`;
    });

    const blob = new Blob([md], { type: 'text/markdown;charset=utf-8;' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = `DockShift_Notes_${protein.pdbId}_${Date.now()}.md`;
    link.click();
    URL.revokeObjectURL(url);
  };

  return (
    <div className="h-full flex flex-col bg-[#0C1423] text-[#F2F7FF] overflow-y-auto">
      {/* Header */}
      <div className="px-6 py-4 border-b border-[#1c2e4a] bg-[#0E1728]/80 flex flex-wrap items-center justify-between gap-4">
        <div>
          <div className="flex items-center gap-2">
            <BookOpen className="w-5 h-5 text-[#63E6DE]" />
            <h1 className="text-lg font-semibold tracking-tight text-[#F2F7FF]">
              Research Notes &amp; Lab Log
            </h1>
            <span className="px-2 py-0.5 text-xs font-mono rounded bg-[#1c2e4a] text-[#63E6DE] border border-[#63E6DE]/20">
              {notes.length} Recorded
            </span>
          </div>
          <p className="text-xs text-[#91A6BE] mt-0.5">
            Log structural observations, pose analyses, mechanistic hypotheses, and next computational experiments.
          </p>
        </div>

        <div className="flex items-center gap-2.5">
          <button
            onClick={() => setIsAdding(!isAdding)}
            className="px-3.5 py-2 text-xs font-mono font-medium rounded-lg bg-[#63E6DE] hover:bg-[#50cfc7] text-[#0C1423] transition flex items-center gap-1.5 shadow-md"
          >
            <Plus className="w-4 h-4" />
            <span>New Note</span>
          </button>
          <button
            onClick={exportNotesAsMarkdown}
            className="px-3 py-2 text-xs font-mono rounded-lg bg-[#152237] hover:bg-[#1c2e4a] text-[#F2F7FF] border border-[#1e3250] transition flex items-center gap-1.5"
          >
            <Download className="w-3.5 h-3.5 text-[#438DFF]" />
            <span>Export .md</span>
          </button>
        </div>
      </div>

      <div className="p-6 max-w-6xl mx-auto w-full space-y-6">
        {/* Search & Category Filter Bar */}
        <div className="flex flex-wrap items-center justify-between gap-3 bg-[#152237] p-3 rounded-xl border border-[#1e3250]">
          <div className="relative flex-1 min-w-[240px]">
            <Search className="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2 text-[#5E7594]" />
            <input
              type="text"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              placeholder="Search notes by keyword, residue, or tag..."
              className="w-full pl-9 pr-3 py-1.5 bg-[#0C1423] border border-[#1e3250] rounded-lg text-xs text-[#F2F7FF] placeholder-[#5E7594] outline-none focus:border-[#63E6DE] font-mono"
            />
          </div>

          <div className="flex items-center gap-1">
            {['ALL', 'Observation', 'Question', 'Hypothesis', 'Next Experiment'].map((cat) => (
              <button
                key={cat}
                onClick={() => setSelectedCategory(cat)}
                className={`px-2.5 py-1 text-xs font-mono rounded-lg transition ${
                  selectedCategory === cat
                    ? 'bg-[#1c2e4a] text-[#63E6DE] font-semibold border border-[#63E6DE]/30'
                    : 'text-[#91A6BE] hover:text-[#F2F7FF]'
                }`}
              >
                {cat}
              </button>
            ))}
          </div>
        </div>

        {/* Create Note Modal / Accordion */}
        {isAdding && (
          <form
            onSubmit={handleCreateSubmit}
            className="p-5 rounded-2xl bg-[#152237] border border-[#63E6DE]/40 shadow-xl space-y-4 animate-fadeIn"
          >
            <div className="flex items-center justify-between pb-2 border-b border-[#1c2e4a]">
              <span className="font-bold text-sm text-[#F2F7FF] flex items-center gap-2">
                <FileText className="w-4 h-4 text-[#63E6DE]" />
                Record New Research Entry
              </span>
              <button
                type="button"
                onClick={() => setIsAdding(false)}
                className="text-[#91A6BE] hover:text-[#F2F7FF]"
              >
                <X className="w-4 h-4" />
              </button>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
              <div className="md:col-span-2">
                <label className="text-[11px] font-mono text-[#91A6BE] block mb-1">
                  Note Title
                </label>
                <input
                  type="text"
                  required
                  value={newTitle}
                  onChange={(e) => setNewTitle(e.target.value)}
                  placeholder="e.g., BIBR1532 Naphthalene Ring Stacking Against Phe870"
                  className="w-full p-2 bg-[#0C1423] border border-[#1e3250] rounded-lg text-xs text-[#F2F7FF] outline-none focus:border-[#63E6DE]"
                />
              </div>

              <div>
                <label className="text-[11px] font-mono text-[#91A6BE] block mb-1">
                  Category
                </label>
                <select
                  value={newCategory}
                  onChange={(e: any) => setNewCategory(e.target.value)}
                  className="w-full p-2 bg-[#0C1423] border border-[#1e3250] rounded-lg text-xs text-[#F2F7FF] outline-none font-mono"
                >
                  <option value="Observation">Observation</option>
                  <option value="Question">Question</option>
                  <option value="Hypothesis">Hypothesis</option>
                  <option value="Next Experiment">Next Experiment</option>
                </select>
              </div>
            </div>

            <div>
              <label className="text-[11px] font-mono text-[#91A6BE] block mb-1">
                Content &amp; Scientific Notes
              </label>
              <textarea
                rows={4}
                required
                value={newContent}
                onChange={(e) => setNewContent(e.target.value)}
                placeholder="Describe your structural observations, coordinates, docking parameter hypotheses, or experimental plans..."
                className="w-full p-3 bg-[#0C1423] border border-[#1e3250] rounded-lg text-xs text-[#F2F7FF] outline-none focus:border-[#63E6DE] resize-none"
              />
            </div>

            <div className="flex justify-end gap-2 pt-1">
              <button
                type="button"
                onClick={() => setIsAdding(false)}
                className="px-3 py-1.5 rounded-lg bg-[#0C1423] text-[#91A6BE] hover:text-[#F2F7FF] text-xs font-mono"
              >
                Cancel
              </button>
              <button
                type="submit"
                className="px-4 py-1.5 rounded-lg bg-[#63E6DE] text-[#0C1423] font-semibold text-xs font-mono shadow-sm"
              >
                Save Entry
              </button>
            </div>
          </form>
        )}

        {/* Notes Feed */}
        <div className="space-y-4">
          {filteredNotes.length === 0 ? (
            <div className="p-8 rounded-2xl bg-[#152237] border border-[#1e3250] text-center space-y-2">
              <BookOpen className="w-8 h-8 text-[#5E7594] mx-auto" />
              <div className="text-sm font-semibold text-[#F2F7FF]">No Research Notes Found</div>
              <p className="text-xs text-[#91A6BE]">
                Try adjusting your search filter or click &ldquo;New Note&rdquo; to record your first observation.
              </p>
            </div>
          ) : (
            filteredNotes.map((note) => {
              const isEditing = editingId === note.id;

              const badgeColors: Record<string, string> = {
                Observation: 'bg-teal-950/60 text-[#63E6DE] border-teal-800/40',
                Question: 'bg-violet-950/60 text-[#A79BEE] border-violet-800/40',
                Hypothesis: 'bg-amber-950/60 text-[#F5AE65] border-amber-800/40',
                'Next Experiment': 'bg-blue-950/60 text-[#438DFF] border-blue-800/40'
              };

              return (
                <div
                  key={note.id}
                  className="p-5 rounded-2xl bg-[#152237] border border-[#1e3250] hover:border-[#253d63] transition space-y-3"
                >
                  {isEditing ? (
                    <div className="space-y-3">
                      <div className="grid grid-cols-3 gap-3">
                        <input
                          type="text"
                          value={editTitle}
                          onChange={(e) => setEditTitle(e.target.value)}
                          className="col-span-2 p-2 bg-[#0C1423] border border-[#1e3250] rounded-lg text-xs font-bold text-[#F2F7FF]"
                        />
                        <select
                          value={editCategory}
                          onChange={(e: any) => setEditCategory(e.target.value)}
                          className="p-2 bg-[#0C1423] border border-[#1e3250] rounded-lg text-xs font-mono text-[#F2F7FF]"
                        >
                          <option value="Observation">Observation</option>
                          <option value="Question">Question</option>
                          <option value="Hypothesis">Hypothesis</option>
                          <option value="Next Experiment">Next Experiment</option>
                        </select>
                      </div>
                      <textarea
                        rows={3}
                        value={editContent}
                        onChange={(e) => setEditContent(e.target.value)}
                        className="w-full p-2.5 bg-[#0C1423] border border-[#1e3250] rounded-lg text-xs text-[#F2F7FF] resize-none"
                      />
                      <div className="flex justify-end gap-2">
                        <button
                          onClick={() => setEditingId(null)}
                          className="px-3 py-1 text-xs font-mono rounded bg-[#0C1423] text-[#91A6BE]"
                        >
                          Cancel
                        </button>
                        <button
                          onClick={() => handleEditSubmit(note.id)}
                          className="px-3 py-1 text-xs font-mono rounded bg-[#63E6DE] text-[#0C1423] font-semibold"
                        >
                          Save Changes
                        </button>
                      </div>
                    </div>
                  ) : (
                    <>
                      <div className="flex items-start justify-between gap-3">
                        <div className="space-y-1">
                          <div className="flex items-center gap-2">
                            <span
                              className={`px-2 py-0.5 text-[10px] font-mono font-semibold rounded border ${
                                badgeColors[note.category] || 'bg-[#1c2e4a] text-[#91A6BE]'
                              }`}
                            >
                              {note.category}
                            </span>
                            <span className="text-[10px] font-mono text-[#5E7594] flex items-center gap-1">
                              <Calendar className="w-3 h-3" />
                              {note.timestamp}
                            </span>
                          </div>
                          <h3 className="text-base font-bold text-[#F2F7FF]">
                            {note.title}
                          </h3>
                        </div>

                        <div className="flex items-center gap-1">
                          <button
                            onClick={() => startEdit(note)}
                            title="Edit Note"
                            className="p-1.5 rounded-lg text-[#91A6BE] hover:text-[#63E6DE] hover:bg-[#1c2e4a] transition"
                          >
                            <Edit3 className="w-3.5 h-3.5" />
                          </button>
                          <button
                            onClick={() => onDeleteNote(note.id)}
                            title="Delete Note"
                            className="p-1.5 rounded-lg text-[#91A6BE] hover:text-red-400 hover:bg-[#1c2e4a] transition"
                          >
                            <Trash2 className="w-3.5 h-3.5" />
                          </button>
                        </div>
                      </div>

                      <p className="text-xs text-[#91A6BE] leading-relaxed whitespace-pre-wrap">
                        {note.content}
                      </p>

                      {note.tags && note.tags.length > 0 && (
                        <div className="flex flex-wrap items-center gap-1.5 pt-2 border-t border-[#1c2e4a]">
                          {note.tags.map((tag) => (
                            <span
                              key={tag}
                              className="px-2 py-0.5 rounded text-[10px] font-mono bg-[#0C1423] text-[#91A6BE] border border-[#1e3250]"
                            >
                              #{tag}
                            </span>
                          ))}
                        </div>
                      )}
                    </>
                  )}
                </div>
              );
            })
          )}
        </div>
      </div>
    </div>
  );
};
