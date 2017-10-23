#!/usr/bin/env python
'''
Connect to a device running JUNOS and export device and interfaces configuration information to a mySQL database.

Use: "python filename sshcredentialsfile commandsfile sqlcredentialsfile"
- SSH and SQL credentials provided in plain text, comma (',') separated, no whitespaces.
- JUNOS commands provided one per line in a "| display set" fashion.
'''

#Imports
import MySQLdb
import paramiko
import threading
import os.path
import subprocess
import datetime
import time
import sys
import re

global_ip_list = []
check_sql = True

def sql_request(query):
	global check_sql
	sql_file = sys.argv[3]
	open_sql_file = open(sql_file, 'r')
	open_sql_file.seek(0)
	sql_host = open_sql_file.readlines()[0].split(',')[0]
	open_sql_file.seek(0)
	sql_username = open_sql_file.readlines()[0].split(',')[1]
	open_sql_file.seek(0)
	sql_password = open_sql_file.readlines()[0].split(',')[2]
	open_sql_file.seek(0)
	sql_database = open_sql_file.readlines()[0].split(',')[3].rstrip("\n")
	try:
		sql_conn = MySQLdb.connect(sql_host, sql_username, sql_password, sql_database)
		cursor = sql_conn.cursor()
		cursor.execute(query)
		results = list(cursor)
		return results
	except MySQLdb.Error, e:
		sql_log_file = open("sql_err.log", "a")
		print >>sql_log_file, str(datetime.datetime.now()) + ": Error %d: %s" % (e.args[0],e.args[1])
		sql_log_file.close()
		check_sql = False
	open_sql_file.close()

def sql_updater(command,values):
	global check_sql
	sql_file = sys.argv[3]
	open_sql_file = open(sql_file, 'r')
	open_sql_file.seek(0)
	sql_host = open_sql_file.readlines()[0].split(',')[0]
	open_sql_file.seek(0)
	sql_username = open_sql_file.readlines()[0].split(',')[1]
	open_sql_file.seek(0)
	sql_password = open_sql_file.readlines()[0].split(',')[2]
	open_sql_file.seek(0)
	sql_database = open_sql_file.readlines()[0].split(',')[3].rstrip("\n")
	try:
		sql_conn = MySQLdb.connect(sql_host, sql_username, sql_password, sql_database)
		cursor = sql_conn.cursor()
		cursor.execute(command,values)
		sql_conn.commit()
	except MySQLdb.Error, e:
		sql_log_file = open("sql_err.log", "a")
		print >>sql_log_file, str(datetime.datetime.now()) + ": Error %d: %s" % (e.args[0],e.args[1])
		sql_log_file.close()
		check_sql = False
	open_sql_file.close()

def ssh_conn(ip):
	ssh_credentials = sys.argv[1]
	ssh_commands = sys.argv[2]

	open_creds = open(ssh_credentials, 'r')
	open_creds.seek(0)
	username = open_creds.readlines()[0].split(',')[0]
	open_creds.seek(0)
	password = open_creds.readlines()[0].split(',')[1].rstrip("\n")
	#Start SSH Connection
	try:
		session = paramiko.SSHClient()
		session.set_missing_host_key_policy(paramiko.AutoAddPolicy())
		session.connect(ip,username = username, password = password)
		connection = session.invoke_shell()
		time.sleep(2)
		open_creds.close()

		#Deal with pager
		connection.send("set cli screen-length 0\n")

		#Send commands
		open_commands = open(ssh_commands, 'r')
		open_commands.seek(0)
		for each_line in open_commands.readlines():
			connection.send(each_line + '\n')
			time.sleep(5)

		#Catch output
		device_output = connection.recv(65535)
		open_commands.close()

		#Warnings and info
		if re.search("unknown command.", device_output):
			print "* No such command on device %s" % ip
		elif re.search("syntax error.", device_output):
			print "* Syntax error found on device %s" % ip
		else:
			print "Done for device %s" % ip

		#Update host info
		ext_dev_hostname = re.search(r"Hostname: (.+)", device_output)
		ext_dev_model = re.search(r"Model: (.+)", device_output)
		ext_dev_os = re.search(r"--- JUNOS (.+) built", device_output)
		dev_hostname = ext_dev_hostname.group(1)
		dev_model = ext_dev_model.group(1)
		dev_os = ext_dev_os.group(1)

		host_update_query = "UPDATE Hosts SET Hostname = %s, Model = %s, DeviceOS = %s WHERE MgmtAddress = %s"
		sql_updater(host_update_query,(dev_hostname,dev_model,dev_os,ip))

		#Filter unit descriptions
		ext_iface_desc_values = re.findall(r"set interfaces (.+) unit (.+) description (.+?)\r", device_output)

		#Get host ID
		hostId_query = "SELECT HostID FROM Hosts WHERE MgmtAddress = '" + ip + "'"
		hostId = sql_request(hostId_query)[0][0]

		#Gather info from each unit found
		for each_unit in ext_iface_desc_values:
			serviceIf = str(each_unit[0])
			unitNum = str(each_unit[1])
			unitDesc = str(each_unit[2])
			
			#Search unit description for unique service identifiers in a "abc123" style
			ext_ius = re.search(r"^.*(\D{3}\d{3}).*$",unitDesc)
			serviceUid = ''
			if ext_ius:
				serviceUid = str(ext_ius.group(1))
			else:
				serviceUid = 'Unknown'
				
			#Search for VLAN configurations
			vlan_rx_id = r"set interfaces " + re.escape(serviceIf) + r" unit " + re.escape(unitNum) + r" (vlan-id|vlan-id-list|vlan-tags outer) (.+?)\r"
			ext_vlan_id = re.search(vlan_rx_id, device_output)
			servVlanType = ''
			serviceVlan = ''
			if ext_vlan_id:
				serviceVlan = str(ext_vlan_id.group(2))
				servVlanType = str(ext_vlan_id.group(1))
			else:
				serviceVlan = 'Not Set'
				servVlanType = 'Not Set'

			#Search for bandwidth policers in a "plc-bw-XXXm/g" style
			bw_pol_rx = r"set interfaces " + re.escape(serviceIf) + r" unit " + re.escape(unitNum) + r" family (.+) policer output (plc-bw-(\d+?)(\D+?))\r"
			ext_bw = re.search(bw_pol_rx, device_output)
			serviceBwPol = ''
			serviceBw = ''
			if ext_bw and str(ext_bw.group(4)) == 'm':
				serviceBwPol = ext_bw.group(2)
				serviceBw = int(ext_bw.group(3))
			elif ext_bw and str(ext_bw.group(4)) == 'g':
				serviceBwPol = ext_bw.group(2)
				serviceBw = int(ext_bw.group(3)) * 1000
			else:
				serviceBwPol = 'Not Set'
				serviceBw = None

			#Search for assigned bandwidth description
			bw_desc_rx = r"set interfaces " + re.escape(serviceIf) + r" unit " + re.escape(unitNum) + r" bandwidth ((\d+?)(\D+?))\r"
			ext_bw_desc = re.search(bw_desc_rx, device_output)
			serviceBwDesc = ''
			if ext_bw_desc and str(ext_bw_desc.group(3)) == 'm':
				serviceBwDesc = str(ext_bw_desc.group(2))
			elif ext_bw_desc and str(ext_bw_desc.group(3)) == 'g':
				serviceBwDesc = str(int(ext_bw_desc.group(2)) * 1000)
			else:
				serviceBwDesc = None
			
			#Search for disabled and deactivated configurations
			disable_rx = r"set interfaces " + re.escape(serviceIf) + r" unit " + re.escape(unitNum) + r" disable\r"
			ext_disable = re.search(disable_rx,device_output)
			deactivate_rx = r"deactivate interfaces " + re.escape(serviceIf) + r" unit " + re.escape(unitNum) + r"\r"
			ext_deactivate = re.search(deactivate_rx,device_output)
			
			if serviceUid == 'Unknown':
				state = 'Not a service'
			else:
				state = 'Active'
			if ext_disable:
				state = 'Disabled'
			if ext_deactivate:
				state = 'Deactivated'

			#Some basic tests
			#if serviceBwDesc != None:
			#   print serviceBwDesc
			#print str(hostId) + " " + serviceIf + " " + unitDesc + " " + unitNum + " " + serviceUid
			#print unitDesc
			#print servVlanType
			#print serviceVlan
			#print serviceBw
			
			info_insert_statement = 'INSERT INTO Units (Host_ID,IfName,UnitNum,UnitDesc,ServiceIus,Vlan_Type,Vlan_ID,BW_Policy,BW_Speed,BW_Desc,State) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON DUPLICATE KEY UPDATE UnitDesc=%s, ServiceIus=%s, Vlan_Type=%s, Vlan_ID=%s, BW_Policy=%s, BW_Speed=%s, BW_Desc=%s, State=%s'

			info_insert_vars = [hostId,serviceIf,unitNum,unitDesc,serviceUid,servVlanType,serviceVlan,serviceBwPol,serviceBw,serviceBwDesc,state,unitDesc,serviceUid,servVlanType,serviceVlan,serviceBwPol,serviceBw,serviceBwDesc,state]

			sql_updater(info_insert_statement,info_insert_vars)

			#Check for erased interface, unit numer, unit description.
			saved_services_query = 'SELECT IfName,UnitNum,UnitDesc FROM Units WHERE Host_ID = ' + str(hostId)  + ' AND State NOT LIKE "Removed%"'
			saved_services = sql_request(saved_services_query)
			for each_saved in saved_services:
				if each_saved not in ext_iface_desc_values:
					ifInactive = each_saved[0]
					unitInactive = each_saved[1]
					descInactive = each_saved[2]
					date_removed = datetime.datetime.fromtimestamp(time.time()).strftime('%Y-%m-%d') #%H:%M
					state = 'Removed on ' + date_removed
					state_update_statement = 'UPDATE Units SET State=%s WHERE IfName=%s AND UnitNum=%s AND UnitDesc=%s'
					state_update_vars = [state,ifInactive,unitInactive,descInactive]
					sql_updater(state_update_statement,state_update_vars)

		#print device_output + "\n"

		#Close SSH session
		session.close()

	#Catch SSH authentication exceptions
	except paramiko.AuthenticationException:
		print "Invalid username or password on device %s" % ip
		print "Closing program."
		check_sql = False

#Threading
def create_threads():
	global global_ip_list
	threads = []
	for ip in global_ip_list:
		th = threading.Thread(target = ssh_conn, args = (ip,))
		th.start()
		threads.append(th)
	for th in threads:
		th.join()

#Gather hosts from DB
hosts_query = "SELECT MgmtAddress FROM Hosts"
saved_hosts = sql_request(hosts_query)
for ip_addr in saved_hosts:
	global_ip_list.append(ip_addr[0])

#Execute program to all hosts
create_threads()

#Check for SQL errors
if check_sql == True:
	print "\nAll parameters were successfully exported to MySQL."
else:
	print "\nThere was a problem exporting data to MySQL.\n* Check the files, database and sql_err.log.\n"
