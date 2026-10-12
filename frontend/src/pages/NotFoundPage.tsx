import { useNavigate } from 'react-router'
import { Compass } from 'lucide-react'
import { Button } from '@/components/ui/Button'
import { EmptyState } from '@/components/ui/feedback'

export function NotFoundPage() {
  const navigate = useNavigate()
  return (
    <EmptyState
      className="h-full"
      icon={<Compass className="size-5" />}
      title="Página no encontrada"
      description="La dirección no corresponde a ninguna sección del panel."
      action={
        <Button variant="secondary" onClick={() => navigate('/')}>
          Ir a la biblioteca
        </Button>
      }
    />
  )
}
