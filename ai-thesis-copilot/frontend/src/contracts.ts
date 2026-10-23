export interface ThesisRequest {
  title: string;
  discipline: string;
  research_question: string;
  goal: string;
  thread_id?: string;
  resume_from_checkpoint?: boolean;
}
export interface SourceItem {
  id: string; title: string; author: string; year: number; source: string; score: number;
}
export interface ReviewSummary {
  word_count: number; citation_count: number; missing_citations: boolean;
  risk_level: string; checks: string[]; notice: string;
}
export interface WorkflowResult {
  thread_id: string; title: string; research_question: string; outline: string[];
  sources: SourceItem[]; draft: string; review: ReviewSummary;
  trace: Array<{node: string; label: string; status: string}>;
}
export type StreamEvent =
  | {type: 'started'; thread_id: string}
  | {type: 'agent'; node: string; label: string; status: string; checkpoint: string}
  | {type: 'sources'; items: SourceItem[]}
  | {type: 'outline'; items: string[]}
  | {type: 'token'; text: string}
  | {type: 'result'; result: WorkflowResult}
  | {type: 'error'; message: string}
  | {type: 'done'};
