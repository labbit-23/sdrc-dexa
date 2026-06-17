'use client'

// ── Add to labbit-main/app/admin/page.js adminSections array: ──────────────
// { label: 'BMD / DEXA', href: '/admin/bmd', icon: '🦴' }
// ─────────────────────────────────────────────────────────────────────────────

import { useState, useEffect, useCallback } from 'react'
import {
  Box, Heading, Input, InputGroup, InputLeftElement,
  Table, Thead, Tbody, Tr, Th, Td,
  Badge, Spinner, Center, Text, HStack,
  useColorMode,
} from '@chakra-ui/react'
import { SearchIcon } from '@chakra-ui/icons'
import Link from 'next/link'
import RequireAuth from '../../../components/RequireAuth'
import ShortcutBar from '../../../components/ShortcutBar'

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

export default function BmdPage() {
  const { colorMode } = useColorMode()
  const isDark = colorMode === 'dark'

  const [patients, setPatients] = useState([])
  const [query, setQuery]       = useState('')
  const [loading, setLoading]   = useState(true)
  const [error, setError]       = useState(null)

  const fetchPatients = useCallback(async (q) => {
    setLoading(true)
    setError(null)
    try {
      const url = q ? `/api/bmd/patients?q=${encodeURIComponent(q)}` : '/api/bmd/patients'
      const res = await fetch(url, { credentials: 'include', cache: 'no-store' })
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const data = await res.json()
      setPatients(data.patients || [])
    } catch (e) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { fetchPatients('') }, [fetchPatients])

  const handleSearch = useCallback((e) => {
    const q = e.target.value
    setQuery(q)
    fetchPatients(q)
  }, [fetchPatients])

  return (
    <RequireAuth roles={['admin', 'manager', 'director']}>
      <Box minH="100vh" bg={isDark ? 'var(--dashboard-shell-bg)' : 'gray.50'}>
        <ShortcutBar />
        <Box maxW="6xl" mx="auto" pt="72px" px={4} pb={8}>

          <HStack justify="space-between" mb={6}>
            <Heading size="lg" color={isDark ? 'white' : 'gray.800'}>
              BMD / DEXA Reports
            </Heading>
            <Text fontSize="sm" color="gray.500">
              {!loading && `${patients.length} patient${patients.length !== 1 ? 's' : ''}`}
            </Text>
          </HStack>

          <InputGroup mb={6} maxW="sm">
            <InputLeftElement pointerEvents="none">
              <SearchIcon color="gray.400" />
            </InputLeftElement>
            <Input
              placeholder="Search name or patient ID…"
              value={query}
              onChange={handleSearch}
              bg={isDark ? 'gray.800' : 'white'}
              borderColor={isDark ? 'gray.600' : 'gray.200'}
            />
          </InputGroup>

          {error && (
            <Text color="red.400" mb={4}>Error loading patients: {error}</Text>
          )}

          {loading ? (
            <Center py={16}><Spinner size="xl" color="teal.400" /></Center>
          ) : patients.length === 0 ? (
            <Center py={16}>
              <Text color="gray.500">
                {query ? 'No patients match that search.' : 'No BMD scans in the database yet.'}
              </Text>
            </Center>
          ) : (
            <Box
              overflowX="auto"
              borderRadius="lg"
              boxShadow="sm"
              bg={isDark ? 'gray.800' : 'white'}
              border="1px solid"
              borderColor={isDark ? 'gray.700' : 'gray.200'}
            >
              <Table size="sm" variant="simple">
                <Thead bg={isDark ? 'gray.700' : 'gray.50'}>
                  <Tr>
                    <Th>Patient</Th>
                    <Th>PID</Th>
                    <Th>DOB</Th>
                    <Th>Sex</Th>
                    <Th>Scans</Th>
                    <Th>Last Scan</Th>
                    <Th>Worst T</Th>
                    <Th>Classification</Th>
                  </Tr>
                </Thead>
                <Tbody>
                  {patients.map(p => (
                    <Tr
                      key={p.id}
                      _hover={{ bg: isDark ? 'gray.700' : 'teal.50' }}
                      cursor="pointer"
                    >
                      <Td fontWeight={600}>
                        <Link href={`/admin/bmd/${p.id}`} style={{ color: 'teal' }}>
                          {p.first_name} {p.last_name}
                        </Link>
                      </Td>
                      <Td color="gray.500" fontSize="xs">{p.patient_id || '—'}</Td>
                      <Td>{fmtDate(p.dob)}</Td>
                      <Td>{p.gender ? p.gender.charAt(0) : '—'}</Td>
                      <Td isNumeric>{p.scan_count}</Td>
                      <Td>{fmtDate(p.last_scan_date)}</Td>
                      <Td>
                        <Text fontWeight="bold" color={tColor(p.worst_t, isDark)}>
                          {p.worst_t != null
                            ? (p.worst_t >= 0 ? '+' : '') + p.worst_t.toFixed(1)
                            : '—'}
                        </Text>
                      </Td>
                      <Td>
                        {p.classification
                          ? <Badge colorScheme={classifyScheme(p.classification)}>{p.classification}</Badge>
                          : <Text color="gray.400">—</Text>}
                      </Td>
                    </Tr>
                  ))}
                </Tbody>
              </Table>
            </Box>
          )}
        </Box>
      </Box>
    </RequireAuth>
  )
}
