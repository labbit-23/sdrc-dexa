'use client'

import { useState, useEffect } from 'react'
import { useParams } from 'next/navigation'
import {
  Box, Heading, Text, HStack, VStack, Badge, Spinner, Center,
  Table, Thead, Tbody, Tr, Th, Td,
  Breadcrumb, BreadcrumbItem, BreadcrumbLink,
  Divider, Button,
  useColorMode,
} from '@chakra-ui/react'
import { ExternalLinkIcon } from '@chakra-ui/icons'
import Link from 'next/link'
import RequireAuth from '../../../../../components/RequireAuth'
import ShortcutBar from '../../../../../components/ShortcutBar'

// ── T-score colour bar ────────────────────────────────────────────────────
const T_MIN = -4, T_MAX = 3

function TScoreBar({ label, t, bmd }) {
  const pct = t != null
    ? Math.max(0, Math.min(100, ((t - T_MIN) / (T_MAX - T_MIN)) * 100))
    : null

  const osteoW = `${((-2.5 - T_MIN) / (T_MAX - T_MIN)) * 100}%`
  const openiaW = `${(1.5 / (T_MAX - T_MIN)) * 100}%`

  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 4 }}>
      <span style={{ fontSize: 12, color: '#9CA3AF', width: 100, flexShrink: 0, textAlign: 'right' }}>
        {label}
      </span>
      <div style={{ position: 'relative', flex: 1, height: 18, borderRadius: 9, overflow: 'hidden',
        display: 'flex', background: '#F3F4F6' }}>
        <div style={{ height: '100%', width: osteoW, background: '#FCA5A5' }} />
        <div style={{ height: '100%', width: openiaW, background: '#FDE68A' }} />
        <div style={{ height: '100%', flex: 1, background: '#BBF7D0' }} />
        {pct != null && (
          <div style={{ position: 'absolute', top: 0, bottom: 0, width: 3,
            background: '#1F2937', borderRadius: 2, left: `calc(${pct}% - 1.5px)` }} />
        )}
      </div>
      <div style={{ width: 90, textAlign: 'right' }}>
        {t != null ? (
          <span style={{ fontSize: 13, fontWeight: 700, color: '#1F2937' }}>
            {t >= 0 ? '+' : ''}{t.toFixed(1)}
            {bmd != null && (
              <span style={{ fontSize: 11, color: '#9CA3AF', marginLeft: 4 }}>
                {bmd.toFixed(3)}
              </span>
            )}
          </span>
        ) : (
          <span style={{ fontSize: 13, color: '#9CA3AF' }}>—</span>
        )}
      </div>
    </div>
  )
}

// ── helpers ───────────────────────────────────────────────────────────────
function classifyScheme(c) {
  if (!c) return 'gray'
  const lc = c.toLowerCase()
  if (lc.includes('osteoporosis')) return 'red'
  if (lc.includes('osteopenia'))   return 'orange'
  return 'green'
}

function fmtDate(iso) {
  if (!iso) return '—'
  return new Date(iso).toLocaleDateString('en-IN', { day: '2-digit', month: 'short', year: 'numeric' })
}

function fmtNum(v, dp = 3) {
  return v != null ? v.toFixed(dp) : '—'
}

function fmtT(t) {
  if (t == null) return '—'
  return (t >= 0 ? '+' : '') + t.toFixed(1)
}

function tColor(t) {
  if (t == null) return 'gray.400'
  if (t <= -2.5) return 'red.400'
  if (t <= -1.0) return 'orange.400'
  return 'green.400'
}

// ── BMD results table for one region ─────────────────────────────────────
function RegionTable({ title, rows, isDark }) {
  if (!rows || rows.length === 0) return null
  const card  = isDark ? 'gray.800' : 'white'
  const border = isDark ? 'gray.700' : 'gray.200'

  return (
    <Box mb={6}>
      <Heading size="xs" mb={3} color={isDark ? 'gray.300' : 'gray.600'}
        textTransform="uppercase" letterSpacing="wide">
        {title}
      </Heading>

      {/* T-score bars */}
      <Box mb={3} px={2}>
        {rows.map(r => (
          <TScoreBar key={r.site} label={r.site} t={r.t_score} bmd={r.bmd} />
        ))}
      </Box>

      {/* Detail table */}
      <Box overflowX="auto" borderRadius="md" border="1px solid" borderColor={border} bg={card}>
        <Table size="xs" variant="simple">
          <Thead bg={isDark ? 'gray.700' : 'gray.50'}>
            <Tr>
              <Th>Site</Th>
              <Th isNumeric>BMD g/cm²</Th>
              <Th isNumeric>T-Score</Th>
              <Th isNumeric>Z-Score</Th>
              <Th isNumeric>BMC g</Th>
              <Th isNumeric>Area cm²</Th>
            </Tr>
          </Thead>
          <Tbody>
            {rows.map(r => (
              <Tr key={r.site}>
                <Td fontWeight={600}>{r.site}</Td>
                <Td isNumeric>{fmtNum(r.bmd)}</Td>
                <Td isNumeric>
                  <Text color={tColor(r.t_score)} fontWeight={700}>{fmtT(r.t_score)}</Text>
                </Td>
                <Td isNumeric>{fmtT(r.z_score)}</Td>
                <Td isNumeric>{fmtNum(r.bmc, 2)}</Td>
                <Td isNumeric>{fmtNum(r.area, 2)}</Td>
              </Tr>
            ))}
          </Tbody>
        </Table>
      </Box>
    </Box>
  )
}

// ── Page ─────────────────────────────────────────────────────────────────
export default function ScanDetailPage() {
  const { colorMode } = useColorMode()
  const isDark = colorMode === 'dark'
  const { id } = useParams()

  const [data, setData]     = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError]   = useState(null)

  useEffect(() => {
    if (!id) return
    fetch(`/api/bmd/scan/${id}`, { credentials: 'include', cache: 'no-store' })
      .then(r => r.json())
      .then(d => {
        if (d.error) throw new Error(d.error)
        setData(d)
      })
      .catch(e => setError(e.message))
      .finally(() => setLoading(false))
  }, [id])

  const bg    = isDark ? 'var(--dashboard-shell-bg)' : 'gray.50'
  const card  = isDark ? 'gray.800' : 'white'
  const border = isDark ? 'gray.700' : 'gray.200'

  if (loading) return (
    <RequireAuth roles={['admin', 'manager', 'director']}>
      <Box minH="100vh" bg={bg}><ShortcutBar />
        <Center pt="100px"><Spinner size="xl" color="teal.400" /></Center>
      </Box>
    </RequireAuth>
  )

  if (error || !data) return (
    <RequireAuth roles={['admin', 'manager', 'director']}>
      <Box minH="100vh" bg={bg}><ShortcutBar />
        <Center pt="100px"><Text color="red.400">{error || 'Scan not found.'}</Text></Center>
      </Box>
    </RequireAuth>
  )

  const { patient, scan, regions } = data

  return (
    <RequireAuth roles={['admin', 'manager', 'director']}>
      <Box minH="100vh" bg={bg}>
        <ShortcutBar />
        <Box maxW="6xl" mx="auto" pt="72px" px={4} pb={8}>

          <Breadcrumb mb={4} fontSize="sm" color="gray.500">
            <BreadcrumbItem>
              <BreadcrumbLink as={Link} href="/admin/bmd">BMD / DEXA</BreadcrumbLink>
            </BreadcrumbItem>
            <BreadcrumbItem>
              <BreadcrumbLink as={Link} href={`/admin/bmd/${patient.id}`}>
                {patient.first_name} {patient.last_name}
              </BreadcrumbLink>
            </BreadcrumbItem>
            <BreadcrumbItem isCurrentPage>
              <Text>{fmtDate(scan.scan_date)}</Text>
            </BreadcrumbItem>
          </Breadcrumb>

          {/* Patient + scan header */}
          <Box bg={card} borderRadius="lg" border="1px solid" borderColor={border} p={5} mb={6}>
            <HStack justify="space-between" wrap="wrap" gap={4}>
              <VStack align="start" spacing={0}>
                <Heading size="md">{patient.first_name} {patient.last_name}</Heading>
                <Text color="gray.500" fontSize="sm">
                  PID {patient.patient_id || '—'} · {patient.gender || '—'} ·
                  DOB {fmtDate(patient.dob)}
                </Text>
                {patient.physician && (
                  <Text color="gray.500" fontSize="sm">Referring: {patient.physician}</Text>
                )}
                <Text color="gray.500" fontSize="xs" mt={1}>
                  Scanned {fmtDate(scan.scan_date)} · {scan.scanner_serial} · {scan.software}
                </Text>
              </VStack>

              <VStack align="end" spacing={2}>
                <Badge
                  colorScheme={classifyScheme(scan.classification)}
                  fontSize="md" px={3} py={1}
                >
                  {scan.classification || '—'}
                </Badge>
                <Text color={tColor(scan.worst_t)} fontWeight={700} fontSize="lg">
                  Worst T = {fmtT(scan.worst_t)}
                </Text>
                {scan.pdf_url && (
                  <Button
                    as="a"
                    href={scan.pdf_url}
                    target="_blank"
                    rel="noreferrer"
                    size="sm"
                    colorScheme="teal"
                    rightIcon={<ExternalLinkIcon />}
                  >
                    Open Report PDF
                  </Button>
                )}
              </VStack>
            </HStack>
          </Box>

          {/* Legend */}
          <HStack mb={4} gap={4} fontSize="xs" color="gray.500">
            <HStack><Box w={3} h={3} borderRadius="sm" bg="red.200" /><Text>Osteoporosis (T ≤ -2.5)</Text></HStack>
            <HStack><Box w={3} h={3} borderRadius="sm" bg="yellow.200" /><Text>Osteopenia (-2.5 &lt; T ≤ -1.0)</Text></HStack>
            <HStack><Box w={3} h={3} borderRadius="sm" bg="green.200" /><Text>Normal (T &gt; -1.0)</Text></HStack>
          </HStack>

          {/* BMD results by region */}
          <RegionTable title="Lumbar Spine (L1 – L4)" rows={regions.spine}       isDark={isDark} />
          <RegionTable title="Left Femur"             rows={regions.left_femur}  isDark={isDark} />
          <RegionTable title="Right Femur"            rows={regions.right_femur} isDark={isDark} />

          {/* Inline PDF viewer */}
          {scan.pdf_url && (
            <>
              <Divider my={6} />
              <Heading size="sm" mb={3} color={isDark ? 'gray.300' : 'gray.600'}>Report</Heading>
              <Box
                as="iframe"
                src={scan.pdf_url}
                w="100%"
                h="900px"
                borderRadius="lg"
                border="1px solid"
                borderColor={border}
              />
            </>
          )}

        </Box>
      </Box>
    </RequireAuth>
  )
}
