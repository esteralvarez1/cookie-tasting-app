import { useEffect, useRef, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { ApiError, api } from './api'
import type { DialogueResponseData, EvaluationData, ParticipantSession, PublicTastingSession, SessionNextStep, Turn } from './types'

type Phase =
  | 'loading_tasting_session'
  | 'participant_setup'
  | 'sample_selection'
  | 'conversation'
  | 'sample_comment'
  | 'done'
  | 'error'

type PersistedState = {
  phase: Phase
  publicToken: string
  tastingSession: PublicTastingSession | null
  participantCode: string
  session: Omit<ParticipantSession, 'session_token'> | null
  pendingCodes: string[]
  evaluation: EvaluationData | null
  turns: Turn[]
  pendingNextStep: string | null
}

const STORAGE_KEY = 'cookie-tasting-clean-app'
const SESSION_TOKEN_KEY = 'ct_session_token'
const SESSION_EXPIRES_KEY = 'ct_session_expires_at'

function isTokenExpired(): boolean {
  const expiresAt = sessionStorage.getItem(SESSION_EXPIRES_KEY)
  if (!expiresAt) return false
  return Date.now() > new Date(expiresAt).getTime()
}

function clearPersistedSession(): void {
  localStorage.removeItem(STORAGE_KEY)
  sessionStorage.removeItem(SESSION_TOKEN_KEY)
  sessionStorage.removeItem(SESSION_EXPIRES_KEY)
}

export default function App() {
  const [searchParams] = useSearchParams()
  const urlToken = searchParams.get('token')

  const [phase, setPhase] = useState<Phase>('loading_tasting_session')
  const [tastingSession, setTastingSession] = useState<PublicTastingSession | null>(null)
  const [participantCode, setParticipantCode] = useState('')
  const [session, setSession] = useState<ParticipantSession | null>(null)
  const [pendingCodes, setPendingCodes] = useState<string[]>([])
  const [selectedSampleCode, setSelectedSampleCode] = useState('')
  const [evaluation, setEvaluation] = useState<EvaluationData | null>(null)
  const [turns, setTurns] = useState<Turn[]>([])
  const [message, setMessage] = useState('')
  const [sampleComment, setSampleComment] = useState('')
  const [statusMessage, setStatusMessage] = useState('')
  const [loading, setLoading] = useState(false)
  const [pendingNextStep, setPendingNextStep] = useState<string | null>(null)
  const messagesEndRef = useRef<HTMLDivElement>(null)

  // On mount: restore from storage if token matches, otherwise fetch public tasting session.
  useEffect(() => {
    if (!urlToken) {
      setPhase('error')
      setStatusMessage('No se encontró un token de sesión en la URL. Contacta con el administrador.')
      return
    }

    const saved = localStorage.getItem(STORAGE_KEY)
    if (saved) {
      try {
        const parsed = JSON.parse(saved) as Partial<PersistedState>
        const token = sessionStorage.getItem(SESSION_TOKEN_KEY)
        const savedSession = parsed.session ?? null
        if (parsed.publicToken === urlToken && savedSession && token) {
          const sessionId = (savedSession as { session_id: string }).session_id
          api.getSessionNextStep(sessionId, token)
            .then(() => {
              setPhase(parsed.phase || 'participant_setup')
              setTastingSession(parsed.tastingSession ?? null)
              setSession({ ...(savedSession as ParticipantSession), session_token: token })
              setEvaluation(parsed.evaluation ?? null)
              setTurns(parsed.turns ?? [])
              setParticipantCode(parsed.participantCode ?? '')
              setPendingCodes(parsed.pendingCodes ?? [])
              setPendingNextStep(parsed.pendingNextStep ?? null)
              if (parsed.phase === 'conversation' && parsed.evaluation?.evaluation_id) {
                api.getEvaluationConversation(parsed.evaluation.evaluation_id, token)
                  .then((res) => setTurns(res.data.turns ?? []))
                  .catch(() => {})
              }
            })
            .catch((error) => {
              if (isExpiredError(error)) {
                clearPersistedSession()
                setTastingSession(parsed.tastingSession ?? null)
                setParticipantCode(parsed.participantCode ?? '')
                setPhase('participant_setup')
                setStatusMessage('Tu sesión ha caducado. Vuelve a introducir tu código.')
              } else {
                // Network error — restore state for offline resilience
                setPhase(parsed.phase || 'participant_setup')
                setTastingSession(parsed.tastingSession ?? null)
                setSession({ ...(savedSession as ParticipantSession), session_token: token })
                setEvaluation(parsed.evaluation ?? null)
                setTurns(parsed.turns ?? [])
                setParticipantCode(parsed.participantCode ?? '')
                setPendingCodes(parsed.pendingCodes ?? [])
                setPendingNextStep(parsed.pendingNextStep ?? null)
              }
            })
          return
        }
      } catch {
        // invalid saved state — fall through to re-fetch
      }
      localStorage.removeItem(STORAGE_KEY)
    }

    api.getPublicTastingSession(urlToken)
      .then((response) => {
        const publicSession = response.data as PublicTastingSession
        setTastingSession(publicSession)
        if (publicSession.status === 'CLOSED') {
          setPhase('error')
          setStatusMessage('Esta cata ya no está activa.')
          return
        }
        setPhase('participant_setup')
      })
      .catch((error) => {
        setPhase('error')
        setStatusMessage(getErrorMessage(error, 'No se pudo cargar la sesión de cata. El enlace puede ser inválido o la sesión estar cerrada.'))
      })
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  // Auto-scroll to the latest message whenever turns change.
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [turns])

  // Persist state changes. session_token stays in sessionStorage only.
  useEffect(() => {
    if (!urlToken || phase === 'loading_tasting_session' || phase === 'error') return
    const { session_token: _t, ...sessionWithoutToken } = session ?? ({} as ParticipantSession)
    const payload: PersistedState = {
      phase,
      publicToken: urlToken,
      tastingSession,
      participantCode,
      session: session ? sessionWithoutToken : null,
      pendingCodes,
      evaluation,
      turns,
      pendingNextStep,
    }
    localStorage.setItem(STORAGE_KEY, JSON.stringify(payload))
  }, [phase, tastingSession, session, participantCode, pendingCodes, evaluation, turns, pendingNextStep]) // urlToken stable after mount

  function handleSessionExpired(): void {
    clearPersistedSession()
    setSession(null)
    setEvaluation(null)
    setTurns([])
    setPendingNextStep(null)
    setPendingCodes([])
    setPhase('participant_setup')
    setStatusMessage('Tu sesión ha expirado. Por favor, introduce de nuevo tu código de participante.')
  }

  function isExpiredError(error: unknown): boolean {
    return error instanceof ApiError && error.kind === 'SESSION_EXPIRED'
  }

  function getErrorMessage(error: unknown, fallback: string): string {
    if (error instanceof ApiError) return error.message
    if (error instanceof Error && error.message) return error.message
    return fallback
  }

  async function handleCreateSession() {
    if (!tastingSession || !urlToken) return
    setLoading(true)
    setStatusMessage('')
    try {
      const response = await api.createSession(participantCode, tastingSession.tasting_session_id)
      const data = response.data as ParticipantSession & { session_token_expires_at?: string }
      sessionStorage.setItem(SESSION_TOKEN_KEY, data.session_token)
      if (data.session_token_expires_at) {
        sessionStorage.setItem(SESSION_EXPIRES_KEY, data.session_token_expires_at)
      }
      setSession(data)

      // Session already fully completed (all evaluations done + all per-sample comments saved).
      if (data.status === 'COMPLETED') {
        clearPersistedSession()
        setPhase('done')
        return
      }

      const pending = data.pending_sample_codes ?? []
      setPendingCodes(pending)

      if (pending.length === 0) {
        // All evaluations are COMPLETED but the session is not yet COMPLETED.
        // The last sample's per-sample comment is still pending — restore that screen.
        const nextStepResponse = await api.getSessionNextStep(data.session_id, data.session_token)
        const nextStepData = nextStepResponse.data as SessionNextStep
        if (nextStepData.next_step === 'SAMPLE_COMMENT' && nextStepData.pending_comment_evaluation_id) {
          const evalResponse = await api.getEvaluation(nextStepData.pending_comment_evaluation_id, data.session_token)
          setEvaluation(evalResponse.data as EvaluationData)
          setPendingNextStep('SESSION_COMPLETED')
          setPhase('sample_comment')
        } else {
          clearPersistedSession()
          setPhase('done')
        }
      } else if (tastingSession.total_samples === 1 && pending.length === 1) {
        // Single-sample session: skip the selection screen
        await startEvaluation(pending[0], data)
      } else {
        setSelectedSampleCode(pending[0] || '')
        setPhase('sample_selection')
      }
    } catch (error) {
      setStatusMessage(getErrorMessage(error, 'No se pudo crear la sesión'))
    } finally {
      setLoading(false)
    }
  }

  async function startEvaluation(
    sampleCode: string,
    overrideSession?: ParticipantSession,
  ) {
    const currentSession = overrideSession ?? session
    if (!currentSession || !tastingSession) return
    if (isTokenExpired()) { handleSessionExpired(); return }
    setLoading(true)
    setStatusMessage('')
    try {
      const response = await api.createEvaluation(
        currentSession.session_id,
        sampleCode,
        currentSession.session_token,
      )
      const data = response.data as EvaluationData & { turns?: Turn[] }
      setEvaluation(data)
      setTurns(data.turns || [])
      setSelectedSampleCode('')
      setPhase('conversation')
    } catch (error) {
      if (isExpiredError(error)) { handleSessionExpired(); return }
      setStatusMessage(getErrorMessage(error, 'No se pudo iniciar la evaluación'))
    } finally {
      setLoading(false)
    }
  }

  function applyDialogueUpdate(data: DialogueResponseData) {
    setEvaluation({
      evaluation_id: data.evaluation_id,
      session_id: data.session_id,
      sample_code: data.sample_code,
      presentation_order: data.presentation_order,
      status: data.status,
      current_state: data.current_state,
      current_modality: data.current_modality,
      next_question: data.next_question,
    })
    setTurns(data.turns || [])
  }

  async function handleSendMessage() {
    if (!evaluation || !session || !message.trim()) return
    if (isTokenExpired()) { handleSessionExpired(); return }
    setLoading(true)
    setStatusMessage('')
    try {
      const response = await api.sendDialog(evaluation.evaluation_id, message, session.session_token)
      const data = response.data as DialogueResponseData
      setMessage('')
      applyDialogueUpdate(data)
      if (data.status === 'COMPLETED') {
        // Always show per-sample comment before advancing, including the last sample.
        setPendingNextStep(data.next_step ?? null)
        setPhase('sample_comment')
      }
    } catch (error) {
      if (isExpiredError(error)) { handleSessionExpired(); return }
      setStatusMessage(getErrorMessage(error, 'No se pudo enviar el turno'))
    } finally {
      setLoading(false)
    }
  }

  async function handleSaveSampleComment() {
    if (!evaluation || !session) return
    if (isTokenExpired()) { handleSessionExpired(); return }
    setLoading(true)
    setStatusMessage('')
    try {
      await api.saveSampleComment(evaluation.evaluation_id, sampleComment, session.session_token)
      const nextStepResponse = await api.getSessionNextStep(session.session_id, session.session_token)
      const nextStep = nextStepResponse.data as SessionNextStep
      // Fallback for legacy sessions without TastingSessionConfig: pending_sample_codes will be [].
      const effectivePending = nextStep.pending_sample_codes.length > 0
        ? nextStep.pending_sample_codes
        : pendingCodes.filter((c) => c !== evaluation.sample_code)
      setSampleComment('')
      setEvaluation(null)
      setTurns([])
      setPendingNextStep(null)
      setPendingCodes(effectivePending)
      if (nextStep.next_step === 'NEXT_SAMPLE') {
        setSelectedSampleCode(effectivePending[0] || '')
        setPhase('sample_selection')
      } else {
        clearPersistedSession()
        setPhase('done')
      }
    } catch (error) {
      if (isExpiredError(error)) { handleSessionExpired(); return }
      setStatusMessage(getErrorMessage(error, 'No se pudo guardar el comentario'))
    } finally {
      setLoading(false)
    }
  }

  const completedCount = tastingSession ? tastingSession.total_samples - pendingCodes.length : 0

  return (
    <div className={phase === 'conversation' ? 'page page--chat' : 'page'}>
      <div className="container">
        <header className="hero">
          <h1>Cata conversacional de galletas</h1>
          {tastingSession?.title && <p>{tastingSession.title}</p>}
        </header>

        {statusMessage && phase !== 'sample_comment' && (
          <div className="error-box">{statusMessage}</div>
        )}

        {phase === 'loading_tasting_session' && (
          <section className="card"><p>Cargando sesión...</p></section>
        )}

        {phase === 'error' && (
          <section className="card">
            <h2>Enlace no válido</h2>
            <p>{statusMessage}</p>
          </section>
        )}

        {phase === 'participant_setup' && tastingSession && (
          <section className="card">
            <h2>Bienvenido/a</h2>
            <p style={{ color: '#4b5563', marginBottom: '0.5rem' }}>
              Introduce tu código de participante para acceder a la cata.
            </p>
            <label>Código de participante</label>
            <input
              value={participantCode}
              onChange={(e) => setParticipantCode(e.target.value)}
              placeholder="P001"
              onKeyDown={(e) => { if (e.key === 'Enter' && participantCode.trim() && !loading) handleCreateSession() }}
            />
            <button disabled={loading || !participantCode.trim()} onClick={handleCreateSession}>
              {loading ? 'Iniciando...' : 'Empezar cata'}
            </button>
          </section>
        )}

        {phase === 'sample_selection' && session && tastingSession && (
          <section className="card">
            <h2>Siguiente muestra</h2>
            <p style={{ color: '#4b5563', fontSize: '0.95rem', marginBottom: '0.25rem' }}>
              Muestra {completedCount + 1} de {tastingSession.total_samples}
            </p>
            <label>¿Qué muestra vas a probar ahora?</label>
            <select
              value={selectedSampleCode}
              onChange={(e) => setSelectedSampleCode(e.target.value)}
            >
              {pendingCodes.map((code) => (
                <option key={code} value={code}>{code}</option>
              ))}
            </select>
            <button
              disabled={loading || !selectedSampleCode}
              onClick={() => startEvaluation(selectedSampleCode)}
            >
              {loading ? 'Iniciando...' : 'Empezar esta muestra'}
            </button>
          </section>
        )}

        {phase === 'conversation' && evaluation && (
          <section className="card">
            <div className="progress-row">
              <span>
                Muestra {evaluation.presentation_order}
                {tastingSession && tastingSession.total_samples > 1 ? ` de ${tastingSession.total_samples}` : ''}
              </span>
              <strong>{evaluation.sample_code}</strong>
            </div>
            <div className="chat-box">
              {turns.map((turn) => (
                <div key={turn.turn_index} className={`bubble ${turn.speaker === 'USER' ? 'user' : 'bot'}`}>
                  <div className="bubble-role">{turn.speaker === 'USER' ? 'Tú' : 'Asistente'}</div>
                  <div>{turn.message_text}</div>
                </div>
              ))}
              <div ref={messagesEndRef} />
            </div>
            <div className="chat-input-area">
              <label>Tu respuesta</label>
              <textarea
                value={message}
                onChange={(e) => setMessage(e.target.value)}
                rows={4}
                placeholder="Escribe aquí tu respuesta..."
              />
              <div className="actions">
                <button disabled={loading || !message.trim()} onClick={handleSendMessage}>
                  {loading ? 'Enviando...' : 'Enviar respuesta'}
                </button>
              </div>
            </div>
          </section>
        )}

        {phase === 'sample_comment' && evaluation && (
          <section className="card">
            <h2>Comentario final de la muestra</h2>
            <p style={{ color: '#4b5563', marginBottom: '1rem' }}>
              Antes de continuar, puedes añadir un comentario final sobre esta muestra. Es opcional.
            </p>
            <label>Comentario <span style={{ color: '#9ca3af', fontWeight: 400 }}>(opcional)</span></label>
            <textarea
              value={sampleComment}
              onChange={(e) => { setSampleComment(e.target.value); setStatusMessage('') }}
              rows={4}
              placeholder="Escribe aquí tu comentario..."
            />
            {statusMessage && <div className="error-box">{statusMessage}</div>}
            <div className="actions" style={{ marginTop: '1rem' }}>
              <button disabled={loading} onClick={handleSaveSampleComment}>
                {loading ? 'Guardando...' : pendingNextStep === 'NEXT_SAMPLE' ? 'Continuar con otra muestra' : 'Finalizar cata'}
              </button>
            </div>
          </section>
        )}

        {phase === 'done' && (
          <section className="card success-box">
            <h2>¡Cata finalizada!</h2>
            <p>Gracias por participar en la cata. Tus respuestas se han guardado correctamente.</p>
            {tastingSession?.final_redirect_url && (
              <a
                href={tastingSession.final_redirect_url}
                target="_blank"
                rel="noopener noreferrer"
                style={{
                  display: 'inline-block',
                  marginTop: '1.25rem',
                  padding: '0.65rem 1.5rem',
                  background: '#1a1a2e',
                  color: '#fff',
                  borderRadius: '8px',
                  fontWeight: 600,
                  textDecoration: 'none',
                  fontSize: '1rem',
                }}
              >
                Siguiente enlace
              </a>
            )}
          </section>
        )}
      </div>
    </div>
  )
}
