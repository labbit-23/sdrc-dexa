'use client'

import { useState, useEffect } from 'react'
import { useParams } from 'next/navigation'
import {
  Box, Heading, Text, HStack, VStack, Badge, Spinner, Center,
  Table, Thead, Tbody, Tr, Th, Td,
  Breadcrumb, BreadcrumbItem, BreadcrumbLink,
  Stat, StatLabel, StatNumber, StatHelpText,
  SimpleGrid, Divider,
  useColorMode,
} from '@chakra-ui/react'
import Link from 'next/link'
import RequireAuth from '../../../../components/RequireAuth'
import ShortcutBar from '../../../../components/ShortcutBar'

function classifyScheme(c) {
  if (!c) return 'gray'
  const lc = c.toLowerCase()
  if (lc.includes('osteoporosis')) return 'red'
  if (lc.includes('osteopenia'))   return 'orange'
  return 'green'
}

function tColor(t, isDark) {
  if (t == null) return isDark ? 'gray.500' : 'gray.400'
  if (t <= -2.5) return 'red.400'
  if (t <= -1.0) return 'orange.400'
  return 'green.400'
}

function fmtDate(iso) {
  if (!iso) return '—'
  return new Date(iso).toLocaleDateString('en-IN', { day: '2-digit', month: 'short', year: 'numeric' })
}

function fmtT(t) {
  if (t == null) return '—'
  return (t >= 0 ? '+' : '') + t.toFixed(1)
}

// Simple SVG trend line for worst T-score over time
function TrendChart({ scans, isDark }) {
  if (!scans || scans.length < 2) return null

  const pts = scans
    .filter(s => s.worst_t != null && s.scan_date)
    .sort((a, b) => new Date(a.scan_date) - new Date(b.scan_date))

  if (pts.length < 2) return null

  const W = 340, H = 80, PAD = 16
  const tMin = Math.min(...pts.map(p => p.worst_t)) - 0.5
  const tMax = Math.max(...pts.map(p => p.worst_t)) + 0.5
  const xScale = (i) => PAD + (i / (pts.length - 1)) * (W - PAD * 2)
  const yScale = (t) => PAD + ((tMax - t) / (tMax - tMin)) * (H - PAD * 2)

  const d = pts.map((p, i) => `${i === 0 ? 'M' : 'L'} ${xScale(i)} ${yScale(p.worst_t)}`).join(' ')
  const lineColor = '#0D7377'
  const textColor = isDark ? '#9CA3AF' : '#6B7280'

  // T = -2.5 reference line
  const refY = yScale(-2.5)
  const showRef = refY > PAD && refY < H - PAD

  return (
    <Box>
      <Text fontSize="xs" color="gray.500" mb={1}>Worst T-Score Trend</Text>
      <svg width={W} height={H} style={{ overflow: 'visible' }}>
        {showRef && (
          <line x1={PAD} y1={refY} x2={W - PAD} y2={refY}
            stroke="#EF4444" strokeWidth={1} strokeDasharray="4 3" opacity={0.6} />
        )}
        <path d={d} fill="none" stroke={lineColor} strokeWidth={2} strokeLinejoin="round" />
        {pts.map((p, i) => (
          <circle key={i} cx={xScale(i)} cy={yScale(p.worst_t)} r={3}
            fill={lineColor} />
        ))}
        {pts.map((p, i) => (
          <text key={i} x={xScale(i)} y={yScale(p.worst_t) - 6}
            fontSize={9} textAnchor="middle" fill={textColor}>
            {fmtT(p.worst_t)}
          </text>
        ))}
      </svg>
    </Box>
  )
}

export default function PatientDetailPage() {
  const { colorMode } = useColorMode()
  const isDark = colorMode === 'dark'
  const { id } = useParams()

  const [patient, setPatient] = useState(null)
  const [scans, setScans]     = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError]     = useState(null)

  useEffect(() => {
    if (!id) return
    fetch(`/api/bmd/patients/${id}`, { credentials: 'include', cache: 'no-store' })
      .then(r => r.json())
      .then(data => {
        if (data.error) throw new Error(data.error)
        setPatient(data.patient)
        setScans(data.scans || [])
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

  if (error || !patient) return (
    <RequireAuth roles={['admin', 'manager', 'director']}>
      <Box minH="100vh" bg={bg}><ShortcutBar />
        <Center pt="100px"><Text color="red.400">{error || 'Patient not found.'}</Text></Center>
      </Box>
    </RequireAuth>
  )

  const bestScan = scans[0]

  return (
    <RequireAuth roles={['admin', 'manager', 'director']}>
      <Box minH="100vh" bg={bg}>
        <ShortcutBar />
        <Box maxW="6xl" mx="auto" pt="72px" px={4} pb={8}>

          <Breadcrumb mb={4} fontSize="sm" color="gray.500">
            <BreadcrumbItem>
              <BreadcrumbLink as={Link} href="/admin/bmd">BMD / DEXA</BreadcrumbLink>
            </BreadcrumbItem>
            <BreadcrumbItem isCurrentPage>
              <Text>{patient.first_name} {patient.last_name}</Text>
            </BreadcrumbItem>
          </Breadcrumb>

          {/* Patient header */}
          <Box bg={card} borderRadius="lg" border="1px solid" borderColor={border} p={6} mb={6}>
            <HStack justify="space-between" wrap="wrap" gap={4}>
              <VStack align="start" spacing={0}>
                <Heading size="md">{patient.first_name} {patient.last_name}</Heading>
                <Text color="gray.500" fontSize="sm">
                  PID {patient.patient_id || '—'} · {patient.gender || '—'} · DOB {fmtDate(patient.dob)}
                </Text>
                {patient.physician && (
                  <Text color="gray.500" fontSize="sm">Referring: {patient.physician}</Text>
                )}
              </VStack>

              {bestScan && (
                <SimpleGrid columns={3} gap={4}>
                  <Stat>
                    <StatLabel>Last Scan</StatLabel>
                    <StatNumber fontSize="md">{fmtDate(bestScan.scan_date)}</StatNumber>
                  </Stat>
                  <Stat>
                    <StatLabel>Worst T</StatLabel>
                    <StatNumber fontSize="md" color={tColor(bestScan.worst_t, isDark)}>
                      {fmtT(bestScan.worst_t)}
                    </StatNumber>
                  </Stat>
                  <Stat>
                    <StatLabel>Status</StatLabel>
                    <StatHelpText mt={1}>
                      <Badge colorScheme={classifyScheme(bestScan.classification)} fontSize="sm">
                        {bestScan.classification || '—'}
                      </Badge>
                    </StatHelpText>
                  </Stat>
                </SimpleGrid>
              )}
            </HStack>

            {scans.length >= 2 && (
              <>
                <Divider my={4} />
                <TrendChart scans={scans} isDark={isDark} />
              </>
            )}
          </Box>

          {/* Scan history */}
          <Heading size="sm" mb={3} color={isDark ? 'gray.300' : 'gray.600'}>
            Scan History ({scans.length})
          </Heading>

          <Box
            bg={card}
            borderRadius="lg"
            border="1px solid"
            borderColor={border}
            overflowX="auto"
          >
            <Table size="sm" variant="simple">
              <Thead bg={isDark ? 'gray.700' : 'gray.50'}>
                <Tr>
                  <Th>Date</Th>
                  <Th>Spine L1-L4 T</Th>
                  <Th>Femur Neck T</Th>
                  <Th>Worst T</Th>
                  <Th>Classification</Th>
                  <Th>PDF</Th>
                </Tr>
              </Thead>
              <Tbody>
                {scans.map(scan => (
                  <Tr key={scan.id} _hover={{ bg: isDark ? 'gray.700' : 'teal.50' }}>
                    <Td>
                      <Link href={`/admin/bmd/scan/${scan.id}`} style={{ color: 'teal', fontWeight: 500 }}>
                        {fmtDate(scan.scan_date)}
                      </Link>
                    </Td>
                    <Td>
                      <Text color={tColor(scan.spine_l14_t, isDark)} fontWeight={600}>
                        {fmtT(scan.spine_l14_t)}
                      </Text>
                    </Td>
                    <Td>
                      <Text color={tColor(scan.femur_neck_t, isDark)} fontWeight={600}>
                        {fmtT(scan.femur_neck_t)}
                      </Text>
                    </Td>
                    <Td>
                      <Text color={tColor(scan.worst_t, isDark)} fontWeight={700}>
                        {fmtT(scan.worst_t)}
                      </Text>
                    </Td>
                    <Td>
                      <Badge colorScheme={classifyScheme(scan.classification)}>
                        {scan.classification || '—'}
                      </Badge>
                    </Td>
                    <Td>
                      {scan.pdf_url
                        ? <a href={scan.pdf_url} target="_blank" rel="noreferrer"
                            style={{ color: 'teal', fontSize: '0.8rem' }}>View PDF</a>
                        : <Text color="gray.400" fontSize="xs">—</Text>}
                    </Td>
                  </Tr>
                ))}
              </Tbody>
            </Table>
          </Box>

        </Box>
      </Box>
    </RequireAuth>
  )
}
