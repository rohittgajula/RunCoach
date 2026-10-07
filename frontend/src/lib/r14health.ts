/**
 * R14 §7–§9 hooks used only by the lazily loaded Health sections (experiments, goals,
 * heart) — kept out of the main bundle. Types live in r14.ts.
 */
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ApiError, api, json } from './auth'
import { periodQs } from './queries'
import type { ISODate } from './types'
import type { Experiment, ExperimentKind, ExperimentResult, ExperimentRule, ExperimentTemplate, Goal, GoalBody, HeartResponse } from './r14'

async function optional<T>(path: string): Promise<T | null> {
  try {
    return await api<T>(path)
  } catch (error) {
    if (error instanceof ApiError && [404, 501, 502, 503, 504].includes(error.status)) return null
    throw error
  }
}

const keep = <T,>(previous: T | undefined) => previous

export const useExperimentTemplates = (enabled = true) =>
  useQuery({ queryKey: ['experiment-templates'], queryFn: () => optional<ExperimentTemplate[]>('/experiments/templates/'), enabled, retry: false, staleTime: 60 * 60_000 })

export const useExperiments = () =>
  useQuery({ queryKey: ['experiments'], queryFn: () => optional<Experiment[]>('/experiments/?status=all'), retry: false })

export const useExperiment = (id: number | null) =>
  useQuery({
    queryKey: ['experiment', id],
    queryFn: () => api<Experiment & { result: ExperimentResult | null }>(`/experiments/${id}/`),
    enabled: id != null,
  })

function useExperimentInvalidate() {
  const client = useQueryClient()
  return () => {
    for (const key of ['experiments', 'experiment-active', 'experiment']) client.invalidateQueries({ queryKey: [key] })
  }
}

export function useStartExperiment() {
  const done = useExperimentInvalidate()
  return useMutation({
    mutationFn: (body: { kind: ExperimentKind; days?: number; start?: ISODate; title?: string; rule?: ExperimentRule }) =>
      api<Experiment>('/experiments/', { method: 'POST', ...json(body) }),
    onSuccess: done,
  })
}

export function useExperimentAction() {
  const done = useExperimentInvalidate()
  return useMutation({
    mutationFn: ({ id, action, decision }: { id: number; action: 'stop' | 'delete' | 'decide'; decision?: 'keep' | 'stop' | null }) =>
      action === 'stop'
        ? api<Experiment>(`/experiments/${id}/stop/`, { method: 'POST' })
        : action === 'delete'
          ? api(`/experiments/${id}/`, { method: 'DELETE' })
          : api<Experiment>(`/experiments/${id}/`, { method: 'PATCH', ...json({ decision }) }),
    onSuccess: done,
  })
}

export const useGoals = (status: 'active' | 'achieved' | 'abandoned' | 'all' = 'all') =>
  useQuery({ queryKey: ['goals', status], queryFn: () => optional<Goal[]>(`/goals/?status=${status}`), retry: false })

function useGoalInvalidate() {
  const client = useQueryClient()
  return () => {
    for (const key of ['goals', 'goal-chip', 'achievements']) client.invalidateQueries({ queryKey: [key] })
  }
}

export function useSaveGoal() {
  const done = useGoalInvalidate()
  return useMutation({
    mutationFn: ({ id, body }: { id?: number; body: GoalBody }) =>
      id ? api<Goal>(`/goals/${id}/`, { method: 'PATCH', ...json(body) }) : api<Goal>('/goals/', { method: 'POST', ...json(body) }),
    onSuccess: done,
  })
}

export function useDeleteGoal() {
  const done = useGoalInvalidate()
  return useMutation({ mutationFn: (id: number) => api(`/goals/${id}/`, { method: 'DELETE' }), onSuccess: done })
}

export function useAddGoalValue() {
  const done = useGoalInvalidate()
  return useMutation({
    mutationFn: ({ id, value, date }: { id: number; value: number; date?: ISODate }) =>
      api<Goal>(`/goals/${id}/values/`, { method: 'POST', ...json({ value, ...(date ? { date } : {}) }) }),
    onSuccess: done,
  })
}

export const useHeart = (period: string) =>
  useQuery({
    queryKey: ['heart', period],
    queryFn: () => optional<HeartResponse>(`/health/heart/?${periodQs(period)}`),
    placeholderData: keep,
    retry: false,
  })

