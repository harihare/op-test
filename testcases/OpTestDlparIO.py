# OpenPOWER Automated Test Project
#
# Contributors Listed Below - COPYRIGHT 2021
# [+] International Business Machines Corp.
#
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or
# implied. See the License for the specific language governing
# permissions and limitations under the License.
#
# IBM_PROLOG_END_TAG
#

'''
OpTestDlpar
---------

This test is to preform and validate dlpar commands on SRIO and Pysical adapters
'''

import unittest
import time
import re
import OpTestConfiguration
import OpTestLogger
from common import OpTestHMC
from common.OpTestSystem import OpSystemState
from common.OpTestError import OpTestError
from common.Exceptions import CommandFailed

log = OpTestLogger.optest_logger_glob.get_logger(__name__)

class OpTestDlpar(unittest.TestCase):

    def setUp(self):
        conf = OpTestConfiguration.conf
        self.cv_SYSTEM = conf.system()
        self.console = self.cv_SYSTEM.console
        self.cv_HMC = self.cv_SYSTEM.hmc
        self.cv_HOST = conf.host()
        self.mg_system = self.cv_HMC.mg_system
        self.dest_lpar = conf.args.target_lpar
        self.pci_device = conf.args.pci_device
        self.sriov = conf.args.sriov
        self.num_of_dlpar = conf.args.num_of_dlpar

        if not self.cv_HMC.is_lpar_in_managed_system(self.mg_system, self.cv_HMC.lpar_name):
            raise OpTestError("Lpar %s not found in managed system %s" % (
                              self.cv_HMC.lpar_name, self.mg_system))
        if not self.cv_HMC.is_lpar_in_managed_system(self.mg_system, self.dest_lpar):
            raise OpTestError("Lpar %s not found in managed system %s" % (self.dest_lpar, self.mg_system))
        self.check_pkg_installation()
        self.rsct_service_start()
        if self.dest_lpar is not None:
            cmd = 'lshwres -r io -m %s --rsubtype slot --filter \
                   lpar_names=%s -F lpar_id' % (self.mg_server, self.dest_lpar)
            output = self.cv_HMC.ssh.run_command(cmd)
            self.dest_lpar_id =  output[0]
        self.loc_code = self.get_slot_from_sysfs(self.pci_device)
        self.get_slot_hw_details()

    def check_pkg_installation(self):
        pkg_found = True
        pkg_notfound= []
        self.oslevel = self.cv_HOST.host_get_OS_Level()
        lpm_pkg_list = ["src", "rsct.core", "rsct.core.utils", "rsct.basic", "rsct.opt.storagerm", "DynamicRM"]
        for pkg in lpm_pkg_list:
            pkg_status = self.cv_HOST.host_check_pkg_installed(self.oslevel, pkg)
            if not pkg_status:
                pkg_found = False
                pkg_notfound.append(pkg)
        if pkg_found:
            return True
        raise OpTestError("Install the required packages : %s" % pkg_notfound)

    def rsct_servcie_start(self):
        rc = self.cv_HOST.host_run_command("lssrc -a")
        if "inoperative" in str(rc):
            self.cv_HOST.host_run_command("startsrc -g rsct_rm; startsrc -g rsct")
            rc = self.cv_HOST.host_run_command("lssrc -a")
            if "inoperative" in str(rc):
                raise OpTestError("LPM cannot continue as some of rsct services are not active")


    def get_slot_hw_details(self):
        if self.sriov == "yes":
            cmd = "lshwres -r sriov --rsubtype logport -m %s \
            --level eth --filter lpar_names=%s -F \
            'adapter_id,logical_port_id,phys_port_id,lpar_id,location_code,drc_name'" \
                   % (self.mg_system, self.cv_HMC.lpar_name)
            output = self.cv_HMC.ssh.run_command(cmd)
            log.info("output = %s" % output)
            for line in output:
                if self.loc_code in line:
                    self.adapter_id = line.split(',')[0]
                    self.logical_port_id = line.split(',')[1]
                    self.phys_port_id = line.split(',')[2]
                    self.lpar_id = line.split(',')[3]
                    self.location_code = line.split(',')[4]
                    self.phb = line.split(',')[5].split(' ')[1]
                    break
            log.info("lpar_id : %s, loc_code: %s",
                          self.lpar_id, self.loc_code)
        else:
            cmd = 'lshwres -r io -m %s --rsubtype slot \
                   --filter lpar_names=%s -F drc_index,lpar_id,drc_name,bus_id' \
                   % (self.mg_system, self.cv_HMC.lpar_name)
            output = self.cv_HMC.ssh.run_command(cmd)
            log.info("output = %s" % output)
            for line in output:
                if self.loc_code in line:
                    self.drc_index = line.split(',')[0]
                    self.lpar_id = line.split(',')[1]
                    self.phb = line.split(',')[3]
                    break
            log.info("lpar_id : %s, loc_code: %s, drc_index: %s, phb: %s",
                     self.lpar_id, self.loc_code, self.drc_index, self.phb)


    def get_slot_from_sysfs(self, full_pci_address):
        devspec = self.cv_HOST.host_run_command("cat /sys/bus/pci/devices/%s/devspec" % full_pci_address)
        slot = self.cv_HOST.host_run_command("cat /proc/device-tree/%s/ibm,loc-code" % devspec[0])
        slot_ibm = re.match(r'((\w+)[.])+(\w+)-[PC(\d+)-]*C(\d+)', slot[0])
        if slot_ibm:
            return slot_ibm.group()
        slot_openpower = re.match(r'(\w+)[\s]*(\w+)(\d*)', slot[0])
        if slot_openpower:
            return slot_openpower.group()
        raise OpTestError("Failed to get slot from: '%s'" % full_pci_address)


class OpTestDlparIO(OpTestDlpar):

    def dlpar_remove(self):
        output = None
        if self.sriov == "yes":
            self.changehwres_sriov(self.mg_system, 'r', self.lpar_id,
                                   self.adapter_id, self.logical_port_id,
                                   self.phys_port_id, 'remove')
            output = self.listhwres_sriov(self.mg_system, self.cv_HMC.lpar_name,
                                          self.logical_port_id)
        else:
            self.changehwres(self.mg_system, 'r', self.lpar_id, self.cv_HMC.lpar_name,
                             self.drc_index, 'remove')
            output = self.listhwres(self.mg_system, self.cv_HMC.lpar_name, self.drc_index)
        if output:
            log.debug(output)
            raise OpTestError("lshwres still lists the PCI device even after dlpar remove")

    def dlpar_add(self):
        output = None
        if self.sriov == "yes":
            self.changehwres_sriov(self.mg_system, 'a', self.lpar_id,
                                   self.adapter_id, self.logical_port_id,
                                   self.phys_port_id, 'add')
            output = self.listhwres_sriov(self.mg_system, self.cv_HMC.lpar_name,
                                          self.logical_port_id)
            if not output:
                raise OpTestError("lshwres fails to list the port_id after dlpar add"
        else:
            self.changehwres(self.mg_system, 'a', self.lpar_id, self.cv_HMC.lpar_name,
                             self.drc_index, 'add')
            output = self.listhwres(self.mg_system, self.cv_HMC.lpar_name, self.drc_index)
            if not output:
                raise OpTestError("lshwres fails to list the drc_index after dlpar add")

    def dlpar_move(self):
        if self.dest_lpar is None:
            return
        self.changehwres(self.mg_system, 'm', self.lpar_id, self.dest_lpar,
                         self.drc_index, 'move')
        output = self.listhwres(self.mg_system, self.cv_HMC.lpar_name, self.drc_index)
        if output:
            log.debug(output)
            raise OpTestError("lshwres still lists the drc in source lpar %s after \
                      dlpar move to destination lpar %s " % self.cv_HMC.lpar_name, self.dest_lpar)
        output = self.listhwres(self.mg_system, self.dest_lpar_id, self.drc_index)
        if not output:
            log.debug(output)
            raise OpTestError("lshwres fails to list the drc in destination lpar %s after \
                       dlpar move" % self.dest_lpar)

        # dlpar move operation from lpar2 to lpar1
        self.changehwres(self.mg_system, 'm', self.dest_lpar_id, self.cv_HMC.lpar_name,
                         self.drc_index, 'move')
        output = self.listhwres(self.mg_system, self.cv_HMC.lpar_name, self.drc_index)
        if not output:
            log.debug(output)
            raise OpTestError("lshwres fails to list the drc in lpar %s after \
                       dlpar move" % self.cv_HMC.lpar_name)
        output = self.listhwres(self.server, self.dest_lpar, self.drc_index)
        if output:
            log.debug(output)
            raise OpTestError("lshwres still lists the drc in dest lpar %s after \
                      dlpar move to source lpar %s" % (self.dest_lpar, self.cv_HMC.lpar_name))

    def listhwres(self, server, lpar, drc_index):
        cmd = 'lshwres -r io -m %s \
               --rsubtype slot --filter lpar_names= %s \
               | grep -i %s' % (server, lpar, drc_index)
        return self.cv_HMC.ssh.run_command(cmd)

    def listhwres_sriov(self, server, lpar, logical_port_id):
        cmd = 'lshwres -r sriov -m %s \
              --rsubtype logport --filter lpar_names= %s --level eth \
              | grep -i %s' % (server, lpar, logical_port_id)
        return self.cv_HMC.ssh.run_command(cmd)

    def changehwres(self, server, operation, lpar_id, lpar, drc_index, msg):
        if operation == 'm':
            cmd = 'chhwres -r io --rsubtype slot -m %s \
               -o %s --id %s -t %s -l %s ' % (server, operation, lpar_id,
                                              lpar, drc_index)
        else:
            cmd = 'chhwres -r io --rsubtype slot -m %s \
                   -o %s --id %s -l %s ' % (server, operation, lpar_id,
                                            drc_index)
        self.cv_HMC.ssh.run_command(cmd)

    def changehwres_sriov(self, server, operation, lpar_id, adapter_id,
                          logical_port_id, phys_port_id, msg):
        if operation == 'r':
            cmd = 'chhwres -r sriov -m %s --rsubtype logport -o r --id %s -a \
                  adapter_id=%s,logical_port_id=%s' \
                  % (server, lpar_id, adapter_id, logical_port_id)
        elif operation == 'a':
            cmd = 'chhwres -r sriov -m %s --rsubtype logport -o a --id %s -a \
                  phys_port_id=%s,adapter_id=%s,logical_port_id=%s, \
                  logical_port_type=eth' % (server, lpar_id, phys_port_id,
                                            adapter_id, logical_port_id)
        self.cv_HMC.ssh.run_command(cmd)

    def runTest(self):
        '''
        DLPAR remove, add and move operations from lpar_1 to lpar_2
        '''
        for _ in range(self.num_of_dlpar):
            self.dlpar_remove()
            self.dlpar_add()
            self.dlpar_move()

class OpTestdrmgr_pci(OpTestDlpar):

    def do_drmgr_pci(self, operation):
        cmd = "echo -e \"\n\" | drmgr -c pci -s %s -%s" % (self.loc_code,
                                                           operation)
        self.cv_HOST.host_run_command(cmd)

    def runTest(self):
        for _ in range(self.num_of_dlpar):
            self.do_drmgr_pci('r')
            self.do_drmgr_pci('a')
        for _ in range(self.num_of_dlpar):
            self.do_drmgr_pci('R')

class OpTestdrmgr_phb(OpTestDlpar):

    def do_drmgr_phb(self, operation):
        cmd = "drmgr -c phb -s \"PHB %s\" -%s" % (self.phb, operation)
        self.cv_HOST.host_run_command(cmd)

    def runTest(self):
        for _ in range(self.num_of_dlpar):
            self.do_drmgr_phb('r')
            self.do_drmgr_phb('a')

class dlpar_suite():
    s=unittest.TestSuite()
    s.addTest(OpTestDlparIO())
    s.addTest(OpTestdrmgr_pci())
    s.addTest(OpTestdrmgr_phb())
    return s        
