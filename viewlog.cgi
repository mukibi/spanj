#!/usr/bin/perl

use strict;
use warnings;

use DBI;
use CGI;
require "./conf.pl";

our($db,$db_user,$db_pwd,$log_d);

my $page = 1;
my %session;
my %auth_params;
my $per_page = 3;
my $authd = 0;
my %log_action_types =
(
"LOGIN"  => {"descr" => "Logged in", "color" => "blue"},

"LOGOUT" => {"descr" => "Logged out","color" => "blue"},

"CHANGE PASSWORD" => {"descr" => "Changed password", "color" => "blue"},

"RESET PASSWORD" => {"descr" => "Password was reset", "color" => "blue"},

"CHANGE SECURITY QUESTIONS" => {"descr" => "Changed security questions","color" => "blue"},

"CHANGE USERNAME" => {"descr" => "Changed username", "color" => "blue"},

"ADD SYSVARS" => {"descr" => "Added a variable to the system", "color" => "green"},

"DELETE SYSVARS" => {"descr" => "Deleted a variable from the system", "color" => "green"},

"ADD TOKEN" => {"descr" => "Added an access token", "color" => "green"},

"DELETE TOKEN" => {"descr" => "Deleted an access token", "color" => "green"},

"EXTEND LEASE" => {"descr" => "Extended lease of an access token", "color" => "green"},

"CREATE STUDENT ROLL" => {"descr" => "Created a new student roll", "color" => "black"},

"DELETE STUDENT ROLL" => {"descr" => "Deleted a student roll", "color" => "black"},

"STUDENT DELETE" => {"descr" => "Deleted a student", "color" => "black"},

"STUDENT UPDATE" => {"descr" => "Altered records of a student", "color" => "black"},

"STUDENT MOVE" => {"descr" => "Moved a student to another class", "color" => "black"},

"STUDENT ADD" => {"descr" => "Added a new student", "color" => "black"},

"UPDATE FEE BALANCES" => {"descr" => "Updated fee balances", "color" => "black"},

"CREATE MARKSHEET" => {"descr" => "Created a marksheet", "color" => "red"},

"EDIT MARKSHEET" => {"descr" => "Edited a marksheet", "color" => "red"},

"VIEW MARKSHEET" => {"descr" => "Viewed marksheet", "color" => "purple"},

"DOWNLOAD REPORT CARDS" => {"descr" => "Downloaded report cards", "color" => "purple"},

"DOWNLOAD MARKSHEET" => {"descr" => "Downloaded marksheet", "color" => "purple"},

"VIEW REPORT CARDS" => {"descr" => "Viewed report cards", "color" => "purple"},

"CREATE NEW FEE BALANCES" => {"descr" => "Created new fee balances", "color" => "purple"},

"ADD TEACHER" => {"descr" => "Added a new teacher", "color" => "fuchsia"},

"DELETE TEACHER" => {"descr" => "Deleted a teacher", "color" => "fuchsia"},

"ADD PROFILE" => {"descr" => "Added a timetable profile" , "color" => "fuchsia"},

"EDIT PROFILE" => {"descr" => "Edited a timetable profile", "color" => "fuchsia"},

"PUBLISH TIMETABLE" => {"descr" => "Published a new timetable", "color" => "fuchsia"},

"UPLOAD DATASET" => {"descr" => "Uploaded a dataset", "color" => "olive"},

"UPDATE DIRECTORY" => {"descr" => "Changed directory primary/unique key", "color" => "olive"},

"CREATE DIRECTORY" => {"descr" => "Created a contacts directory", "color" => "olive"},

"DELETE CONTACT" => {"descr" => "Deleted a contact", "color" => "olive"},

"EDIT CONTACT" => {"descr" => "Edited a contact", "color" => "olive"},

"ADD CONTACT" => {"descr" => "Added a new contact", "color" => "olive"},

"UPLOAD CONTACTS" => {"descr" => "Uploaded a CSV file with contacts", "color" => "olive"},

"CREATE MESSAGING JOB" => {"descr" => "Created a new messaging job", "color" => "olive"},

"RESUME MESSAGING JOB" => {"descr" => "Resumed a suspended messaging job", "color" => "olive"},

"RESTART MESSAGING JOB" => {"descr" => "Restarted a messaging job", "color" => "olive"},

"SUSPEND MESSAGING JOB" => {"descr" => "Suspended a messaging job", "color" => "olive"},

"CREATE SEMATIME.COM MESSAGING JOB" => {"descr" => "Create a new sematime.com messaging job", "color" => "olive"},

"USSD REQUEST" => {"descr" => "Made a USSD request", "color" => "olive"},

"MODEM DISCONNECT" => {"descr" => "Disconnected a modem", "color" => "olive"},

"MODEM CONNECT" => {"descr" => "Connected a modem", "color" => "olive"},

"MODEM UNLOCK" => {"descr" => "Unlocked a modem", "color" => "olive"},

"WRITE RECEIPT" => {"descr" => "Wrote a receipt", "color" => "blue"},

"ROLLBACK RECEIPT" => {"descr" => "Rolled back a receipt", "color" => "blue"},

"WRITE PAYMENT VOUCHER" => {"descr" => "Wrote a payment voucher", "color" => "green"},

"VIEW BALANCES" => {"descr" => "Viewed/printed students' fee balances", "color" => "olive"},

"DOWNLOAD BALANCES" => {"descr" => "Downloaded students' fee balances", "color" => "olive"},

"VIEW FEE STATEMENTS" => {"descr" => "Viewed/printed fee statements", "color" => "olive"},

"UPDATE BALANCES" => {"descr" => "Updated students' fee balances", "color" => "purple"},

"PUBLISH BUDGET" => {"descr" => "Published a new Budget", "color" => "fuchsia"},

"UPDATE BUDGET" => {"descr" => "Updated the current budget Budget", "color" => "fuchsia"},

"PUBLISH FEE STRUCTURE" => {"descr" => "Published a new fee structure", "color" => "fuchsia"},

"BUDGET COMMITMENT" => {"descr" => "Recorded a new budget commitment", "color" => "red"},

"BANK DEPOSIT" => {"descr" => "Recorded a bank deposit", "color" => "red"},

"BANK WITHDRAWAL" => {"descr" => "Recorded a bank withdrawal", "color" => "red"},

"VIEW CASHBOOK" => {"descr" => "Viewed a cashbook", "color" => "red"},

"DOWNLOAD CASHBOOK" => {"descr" => "Downloaded a cashbook", "color" => "red"},

"VIEW FEE REGISTER" => {"descr" => "View students' fee register", "color" => "olive"}

);

my @bursar_acts = ("WRITE RECEIPT","ROLLBACK RECEIPT", "WRITE PAYMENT VOUCHER", "VIEW BALANCES", "DOWNLOAD BALANCES", "VIEW FEE STATEMENTS", "UPDATE BALANCES", "PUBLISH BUDGET", "UPDATE BUDGET", "PUBLISH FEE STRUCTURE", "BANK DEPOSIT", "BANK WITHDRAWAL", "VIEW CASHBOOK", "DOWNLOAD CASHBOOK", "VIEW FEE REGISTER");

my $mode_str = "";
my $query_mode = 0;

my $id = undef;

if ( exists $ENV{"HTTP_SESSION"} ) {

	my @session_data = split/&/,$ENV{"HTTP_SESSION"};
	my @tuple;
	for my $unprocd_tuple (@session_data) {
		#came to learn (as often happens, purely by accident)
		#doing a split/=/,x= will give a list with a size of 1
		#desirable here (where it's OK to ignore unset vars)
		#would be awful where even a blank var means something (e.g
		#logging in with a blank password)
		@tuple = split/\=/,$unprocd_tuple;

		if (@tuple == 2) {
			$tuple[0] =~ s/%([A-Fa-f0-9]{2})/chr(hex($1))/ge;
			$tuple[1] =~ s/%([A-Fa-f0-9]{2})/chr(hex($1))/ge;
			$session{$tuple[0]} = $tuple[1];		
		}
	}
	if ( exists $session{"id"} and $session{"id"} eq "1" or $session{"id"} eq "2" ) {
		$id = $session{"id"};
		$authd++;
	}
	if (exists $session{"vw_per_page"} and $session{"vw_per_page"} =~ /^(\d+)$/) {
		$per_page = $1;
	}
}

unless ($authd) {
	print "Status: 302 Moved Temporarily\r\n";
	print "Location: /login.html?cont=/cgi-bin/viewlog.cgi\r\n";
	print "Content-Type: text/html; charset=ISO-8859-1\r\n";
       	my $res = 
               	"<html>
               	<head>
		<title>Spanj: Exam Management Information System - Redirect Failed</title>
		</head>
         	<body>
                You are not authorized to acesss this resource. Go to the <a href=\"/login.html?cont=/viewlog.cgi\">Login Page</a> to continue. 
		</body>
                </html>";

	my $content_len = length($res);	
	print "Content-Length: $content_len\r\n";
	print "\r\n";
	print $res;
	exit 0;
}

my $user_limit = "";
my ($from_date_limit, $to_date_limit) = ("", "");
my %action_limit = ();
my $query_mode_str = 0;

if ( exists $ENV{"QUERY_STRING"} ) {
	if ( $ENV{"QUERY_STRING"} =~ /\&?pg=(\d+)\&?/ ) {	
		$page = $1;
	}
	if ( $ENV{"QUERY_STRING"} =~ /\&?per_page=(\d+)\&?/ ) {
		$per_page = $1;
		$session{"vw_per_page"} = $per_page;
	}
	if ( $ENV{"QUERY_STRING"} =~ /\&?mode=query\&?/i ) {
		#user has posted some data in query mode
		#reset old prefs
		if (exists $ENV{"REQUEST_METHOD"} and uc($ENV{"REQUEST_METHOD"}) eq "POST") {
			delete @session{"user_limit", "from_date_limit", "to_date_limit", "action_limit"};
		}
		else {
		my $lims = 0;
		if (exists $session{"user_limit"}) {
			$user_limit = $session{"user_limit"};
			$lims++;
		}
		if (exists $session{"from_date_limit"}) {
			$from_date_limit = $session{"from_date_limit"};
			if (exists $session{"to_date_limit"}) {
				$to_date_limit = $session{"to_date_limit"};
				$lims++;
			}	
		}
		if (exists $session{"action_limit"}) {
		
			my $act_lim_line = $session{"action_limit"}; 
			#discovered the 'odd' behaviour of perl session variables-
			#they're HTTP compliant: no spaces, non-ASCII chars are
			#hex-coded
			
			my $space = " ";
			$act_lim_line =~ s/\+/$space/ge;
			$act_lim_line =~ s/%([A-Fa-f0-9]{2})/chr(hex($1))/ge;	
			
			my @act_lims = split/,/,$act_lim_line;
			for my $act_lim (@act_lims) {
				
				$action_limit{$act_lim}++;
				$lims++;
			}
		}
		if ($lims) {	
			$query_mode++;
			$mode_str = "&mode=query";	
		}
		}
	}
}

if (exists $ENV{"REQUEST_METHOD"} and uc($ENV{"REQUEST_METHOD"}) eq "POST") {	

	my $str = "";

	while (<STDIN>) {
               	$str .= $_;
       	}

	my $space = " ";
	$str =~ s/\x2B/$space/ge;
	my @auth_req = split/&/,$str;

	for my $auth_req_line (@auth_req) {
		my $eqs = index($auth_req_line, "=");	
		if ($eqs > 0) {
			my ($k, $v) = (substr($auth_req_line, 0, $eqs), substr($auth_req_line, $eqs + 1)); 
			$k =~ s/%([A-Fa-f0-9]{2})/chr(hex($1))/ge;
			$v =~ s/%([A-Fa-f0-9]{2})/chr(hex($1))/ge;
			$auth_params{$k} = $v;
		}
	}
}

opendir(my $dirh, "$log_d/") || print STDERR "Cannot opendir($log_d/): $!";
my @files = grep {/^user_actions-\d+-\d{2}-\d{2}\.log$/} readdir $dirh;

my $day_count = scalar(@files);
 
my @sorted_files = sort {$b cmp $a} @files;

my @selec = ();
my $offset = 0;
my $cntr = 0;

if ($page > 1) {
	$offset = $per_page * ($page -1);
}

my %events;
my %user_names;

my $query_feedback = '';
my ($from_date_error, $to_date_error) = ("", "");
my $runnable_query = 1;
my @errors;
my %unresolved_unames;

#load query vars into local vars
#update session
#
if (exists $auth_params{"run_query"}) {
	if (exists $session{"confirm_code"} and exists $auth_params{"confirm_code"}) {	
		if ($session{"confirm_code"} eq $auth_params{"confirm_code"}) {
			my $lims = 0;	
			if (exists $auth_params{"user_limit"}) { 
			 	$user_limit = $auth_params{"user_limit"};
				$lims++;
				my $u_limit = $user_limit;
				$u_limit =~ s/&//g;  
				$session{"user_limit"} = $u_limit;
			}
			if (exists $auth_params{"from_date_limit"}) {
				$from_date_limit = $auth_params{"from_date_limit"};
				my $frm_date = $from_date_limit;
				$frm_date =~ s/&//g;
				$session{"from_date_limit"} = $frm_date;
				if (exists $auth_params{"to_date_limit"} ) {
					$to_date_limit = $auth_params{"to_date_limit"};
					my $to_date = $to_date_limit;
					$to_date =~ s/&//;
					$session{"to_date_limit"} = $to_date;
				}
				$lims++;
			}
			for my $param (keys %auth_params) {
				if ($param =~ /^action_limit_\d+$/) {
					my $act = uc($auth_params{$param});
					if (exists $log_action_types{$act}) {
						$lims++;
						$action_limit{$act}++;
					}
				}
			}
			if (keys %action_limit) {
				my $acts_lst = join(',', keys  %action_limit);	
				$session{"action_limit"} = $acts_lst;
			}
			if ($lims) {
				$query_mode++;
				$mode_str = "&mode=query";
			}
		}
		else {
			push @errors, "Do not alter any of the hidden values in the HTTP form; they help with authentication.";
			$runnable_query = 0;
		}
	}
	else {
		push @errors, "Refresh your access tokens by reloading the webpage.";
		$runnable_query = 0;
	}
}

if ($query_mode) {
	my ($user_limd, $date_limd, $action_limd) = (0, 0, 0);
	my ($reform_from_date, $reform_to_date) = ("","");
	my %date_list;		

	if ($user_limit ne "")  {
		$user_limd++;
				
		#users may only be aware of usernames, the 
		#system knows user ids, these are matched below
		my $con = DBI->connect("DBI:mysql:database=$db;host=localhost", $db_user, $db_pwd, {'RaiseError'=>1, 'AutoCommit'=> 0});		
		if ($con) {
			my $prep_stmt2 = $con->prepare("SELECT u_id,u_name FROM users WHERE u_id=? OR u_name LIKE ?");
		
			if ($prep_stmt2) {
				my $rc2 = $prep_stmt2->execute($user_limit, "%$user_limit%");
				if ($rc2) {
					while (my @rslts = $prep_stmt2->fetchrow_array()) {
						$user_names{$rslts[0]} = $rslts[1];	
					}
				}
				else {
					print STDERR "Could not execute SELECT FROM users: ", $prep_stmt2->errstr, $/;
				}
			}
			else {
				print STDERR "Could not prepare SELECT FROM users: ", $prep_stmt2->errstr, $/; 
			}

			my $prep_stmt3 = $con->prepare("SELECT value,issued_to FROM tokens WHERE value=? OR issued_to LIKE ?");

			if ($prep_stmt3) {
				my $rc3 = $prep_stmt3->execute($user_limit, "%$user_limit%");
				if ($rc3) {
					while (my @rslts1 = $prep_stmt3->fetchrow_array()) {
						$user_names{$rslts1[0]} = $rslts1[1];
					}
				}
				else {
					print STDERR "Could not execute SELECT FROM tokens: ", $prep_stmt3->errstr, $/;
				}
			}
			else {
				print STDERR "Could not prepare SELECT FROM tokens: ", $prep_stmt3->errstr, $/;  
			}
		}
		else {
			$user_names{$user_limit}++;
			print STDERR "Cannot connect: $con->strerr$/";
		}	
	}

			
	if ($from_date_limit ne "") { 
		my @today = localtime;	

		$reform_to_date = sprintf "%d-%02d-%02d", $today[5] + 1900, $today[4] + 1, $today[3];
		my $to_date_limit_alt = sprintf "%02d-%02d-%d", $today[3], $today[4] + 1, $today[5] + 1900;

		if ($from_date_limit =~ m!\d{1,2}/\d{1,2}/\d{4}!) {
			$date_limd++;
			$reform_from_date = join('-', reverse(split /\//, $from_date_limit));	
	
			if ($to_date_limit =~ m!\d{1,2}/\d{1,2}/\d{4}!) {
				$reform_to_date = join('-', reverse(split /\//, $to_date_limit));			
			}
			else {
				$to_date_limit = $to_date_limit_alt;
				$to_date_error = "*";
				push @errors, "Invalid 'to' date. Assuming current date ($to_date_limit)";			
			}	
			unless ($reform_to_date ge $reform_from_date) {
				push @errors, "The 'to' date should be greater than/equal to the 'from' date to generate (reasonable) output.";
				$to_date_error = "*";
				$from_date_error = "*";
				my $tmp = $reform_from_date;
				$reform_from_date = $reform_to_date;
				$reform_to_date = $tmp;
				$tmp = $from_date_limit;
				$from_date_limit = $to_date_limit;
				$to_date_limit = $tmp;
			}
			%date_list = get_intervening_list($reform_from_date, $reform_to_date, 1);
		}
		else {
			$from_date_error = "*";
			$from_date_limit = "";
			$to_date_limit = "";
			$runnable_query = 0;
			push @errors, "Invalid 'from' date. A valid date is of the form dd/mm/yyyy e.g 21/12/1989 (December 21<sup>st</sup>, 1989)";			
		}
	}	

	if (keys %action_limit) {
		$action_limd++;
	}
	if ($runnable_query) {

		$day_count = 0;	
		my %matched_days = ();

		if (@errors) {
			$query_feedback .= '<p><span style="font-weight: bold">Query executed despite the following issues(s):<br></span>';
			$query_feedback .= '<ul>';
			for my $error (@errors) {
				$query_feedback .= "<li>$error";
			}
			$query_feedback .= '</ul>';
		}
	
	F:	for my $file  (@sorted_files) {
			my $date = "";
			if ($file =~ /^user_actions-(\d+-\d{2}-\d{2})\.log$/) {
				$date = $1;
			}
			if ($date_limd) {
				unless (exists $date_list{$date}) {
					next F;
				}
			}
			open (my $fh, "$log_d/$file");
			if ($fh) {
				while (<$fh>) {
					chop;
					my $user_end   =  index($_, ' ');
					my $user = substr($_, 0, $user_end);	
					my $time_start = rindex($_, ' ');
					my $time = substr($_, $time_start + 1);
					my $event_ky = $time . "_" . $cntr;
					$time = substr($time, rindex($time, "-") + 1, -3). "h";	
					my $details = substr($_, $user_end + 1, $time_start - 1);

					#check for user match request			
					my ($user_match, $action_match) = (1,1);
					if ($user_limd) {
						unless (exists $user_names{$user}) {
							$user_match = 0;
						}
					}
					#check action type match
					if ($action_limd) {
						$action_match = 0;
				K:		for my $act (keys %action_limit) {
							if ($details =~ /^$act/) {
								$action_match++;
								unless ($user_limd) {
									$unresolved_unames{$user}++
								}
								last K;
							}
						}
					}
					if ($user_match and $action_match) {	
						#add this to list of days with matching 
						#results, increment the day_count
						if (not exists $matched_days{$date}) {
							$matched_days{$date}++;
							$day_count++;
						}
						#interesting issues when $per_page=1 and $page=1
						#handle it specially
						#comments are a beautiful thing...if properly used
							
						if ( ($day_count >= $offset) and ($day_count <= ($page * $per_page)) ) {
							#bursar?
							if ($id  eq "2") {
								#can only view bursar actions
								foreach (@bursar_acts) {
									if ($details =~ /^$_/) {
										$events{$event_ky} = [$user, $details, $time];
										$cntr++;
										last;
									}
								}
							}
							else {
								my $is_bursar_act = 0;
								foreach (@bursar_acts) {
									if ($details =~ /^$_/) {
										$is_bursar_act++;
										last;
									}
								}
								unless ($is_bursar_act) {
									$events{$event_ky} = [$user, $details, $time];
									$cntr++;
								}
							}
							
						}
					}	
				}
			}
			else {
				print STDERR "Could not open('$log_d/$file'): $!$/";
			}
		}
	}
	else {
		$query_feedback .= '<p><span style="color: red">Could not run query due to the following error(s):<br></span>';
		$query_feedback .= '<ul>';
		for my $error (@errors) {
			$query_feedback .= "<li>$error";
		}
		$query_feedback .= '</ul>';

	}
}


else { 

#splicing beyond the edge of the array throws
#an exception. Avoid this by ensuring the array
#offset is within bounds. 
#Miss ArrayOutOfBoundsException?

	my $debug_cntr = 0;
	@selec = @sorted_files;
 
	if ( ($offset + $per_page) >= scalar(@sorted_files)) {
		@selec = splice(@sorted_files, $offset, $per_page);
	}
   #unless ( ($offset + $per_page) >= scalar(@sorted_files)) {
	
	if (@selec) {
		for my $file (@selec) {
			my $date = "";
			if ($file =~ /^user_actions-(\d+-\d{2}-\d{2})\.log$/) {
				$date = $1;
			}
		
			open (my $fh, "$log_d/$file");
			if ($fh) {
				while (<$fh>) {	
					chop;

					my $user_end   =  index($_, "\x20");	
					my $user = substr($_, 0, $user_end);
					$user_names{$user}++;

					my $time_start = rindex($_, "\x20");
					my $time = substr($_, $time_start + 1);
					my $event_ky = $time . "_" . $cntr;

					my $time_prop = substr($time, rindex($time, "-") + 1, -3). "h";	
					my $len = ($time_start - $user_end) - 1; 
					my $details = substr($_, $user_end + 1, $len);
			
					if ($id  eq "2") {
						#can only view bursar actions
						foreach (@bursar_acts) {
							if ($details =~ /^$_/) {
								$events{$event_ky} = [$user, $details, $time];
								$cntr++;
								last;
							}
						}
					}
					else {
						my $is_bursar_act = 0;
						foreach (@bursar_acts) {
							if ($details =~ /^$_/) {
								$is_bursar_act++;
								last;
							}
						}
						unless ($is_bursar_act) {
							$events{$event_ky} = [$user, $details, $time];
							$cntr++;
						}
					}	
				}
			}
			else {
				print STDERR "Could not open('$log_d/$file'): $!$/";
			}
		}
		%unresolved_unames = %user_names;
	}
    #}
}

#resolve ids

if (keys %unresolved_unames) { 
	my $con = DBI->connect("DBI:mysql:database=$db;host=localhost", $db_user, $db_pwd, {'RaiseError'=>1, 'AutoCommit'=> 0});		

	if ($con) {
		my @where_clause_bts =();
		my $where_clause = "";	

		for my $user (keys %unresolved_unames) {
			push @where_clause_bts, "u_id=?";
		}
			
		$where_clause = join (' OR ', @where_clause_bts);

		my $prep_stmt2 = $con->prepare("SELECT u_id,u_name FROM users WHERE $where_clause");

		if ($prep_stmt2) {
			my $rc2 = $prep_stmt2->execute(keys %unresolved_unames);
			if ($rc2) {
				while (my @rslts = $prep_stmt2->fetchrow_array()) {
					$user_names{$rslts[0]} = $rslts[1];	
					delete $unresolved_unames{$rslts[0]}; 
				}
			}
			else {
				print STDERR "Could not execute SELECT FROM users: ", $prep_stmt2->errstr, $/;
			}
		}
		else {
			print STDERR "Could not prepare SELECT FROM users: ", $prep_stmt2->errstr, $/;  
		}

		my @unresolved_unames_arr = keys %unresolved_unames;

		if (@unresolved_unames_arr) {
			my $where_clause1 = "";	
			my @where_clause_bts1;
			foreach (@unresolved_unames_arr) {
				push @where_clause_bts1, "value=?";
			}
		
			$where_clause1 = join (' OR ', @where_clause_bts1);

			my $prep_stmt3 = $con->prepare("SELECT value,issued_to FROM tokens WHERE $where_clause1");

			if ($prep_stmt3) {
				my $rc3 = $prep_stmt3->execute(@unresolved_unames_arr);
				if ($rc3) {
					while (my @rslts1 = $prep_stmt3->fetchrow_array()) {
						$user_names{$rslts1[0]} = $rslts1[1];	
					}
				}
				else {
					print STDERR "Could not execute SELECT FROM tokens: ", $prep_stmt3->errstr, $/;
				}
			}
			else {
				print STDERR "Could not prepare SELECT FROM tokens: ", $prep_stmt3->errstr, $/;  
			}
		}
		$con->disconnect();
	}

	else {
		print STDERR "Cannot connect: $con->strerr$/";
	}
}

my $events_table = '';

my @today = localtime;
my $curr_date = sprintf "%d-%02d-%02d", $today[5] + 1900, $today[4] + 1, $today[3];

my $prev_date = "";

my $table_section_cntr = 0;

if ($cntr > 0) {
	$events_table .= '<table border="1" cellpadding="2%">';
	for my $event (sort {$b cmp $a} keys %events) {
		my $date_seen = "";
		if ($event =~ /^([^_]+)_(.+)$/) {
			$date_seen =  $1;
			$date_seen = substr($date_seen, 0, rindex($date_seen, "-"));	
		}
		if ($date_seen ne $prev_date) {
			#close previous table section
			if ($table_section_cntr++ > 0) {
				$events_table .= '</tbody>';
			}

			my $friendly_date = get_intervening($curr_date, $date_seen); 
			$events_table .= qq{<thead><th colspan="4" style="padding: 2%">$friendly_date</thead><thead><th>User<th>Action<th>Time<th>Details</thead><tbody>};
			$prev_date = $date_seen;
		}
		my @event_elems = @{$events{$event}};
		my $u_name = "";
		if ( exists $user_names{$event_elems[0]} ) {
			$u_name = "($user_names{$event_elems[0]})";	
		}

		my $action = "--";
		my $color = "black";

		for my $log_act ( keys %log_action_types) {
			if ($event_elems[1] =~ /^$log_act/) {
				$action = ${$log_action_types{$log_act}}{"descr"};
				$color  = ${$log_action_types{$log_act}}{"color"};
				last;
			}
		}

		$events_table .= qq{<tr><td>$event_elems[0]$u_name<td style='color: $color'>$action<td>$event_elems[2]<td>$event_elems[1]};
	}
	$events_table .= '</table>';
}
else {
	$events_table = '<em>No events to display</em>'
}
  
my $per_page_guide = '';

if ($day_count > 1) {
	$per_page_guide .= "<p><em>Days per page</em>: <span style='word-spacing: 1em'>";
	for my $row_cnt (1, 3, 7, 10) {
		if ($row_cnt == $per_page) {
			$per_page_guide .= " <span style='font-weight: bold'>$row_cnt</span>";
		}
		else {
			my $re_ordered_page = $page;	
			if ($page > 1) {
				my $preceding_results = $per_page * ($page - 1);
				$re_ordered_page = $preceding_results / $row_cnt;
				#if results will overflow into the next
				#page, bump up the page number
				#save that as an integer
				$re_ordered_page++ unless ($re_ordered_page < int($re_ordered_page));
				$re_ordered_page = int($re_ordered_page);	
			}
			$per_page_guide .= " <a href='/cgi-bin/viewlog.cgi?pg=$re_ordered_page&per_page=$row_cnt$mode_str'>$row_cnt</a>";
		}
	}
	$per_page_guide .= "</span>";
}


my $res_pages = 1;
#simple logic
#if the remaining results ($day_count - x) overflow the current page (x = $page * $per_page)
#and you are on page 1 then this' a multi_page setup

$res_pages = $day_count / $per_page;

if ($res_pages > 1) {
	if (int($res_pages) < $res_pages) {
		$res_pages = int($res_pages) + 1;
	}
}

my $page_guide = '';

if ($res_pages > 0) {
	$page_guide .= '<table cellspacing="50%"><tr>';

	if ($page > 1) {
		$page_guide .= "<td><a href='/cgi-bin/viewlog.cgi?pg=". ($page - 1) ."$mode_str'>Prev</a>";
	}

	if ($page < 10) {
		for (my $i = 1; $i <= $res_pages and $i < 11; $i++) {
			if ($i == $page) {
				$page_guide .= "<td><span style='font-weight: bold'>$i</span>";
			}
			else {
				$page_guide .= "<td><a href='/cgi-bin/viewlog.cgi?pg=$i$mode_str'>$i</a>";
			}
		}
	}
	else {
		for (my $i = $page - 4; $i <= $res_pages and $i < ($page + 4); $i++) {
			if ($i == $page) {
				$page_guide .= "<td><span style='font-weight: bold'>$i</span>";
			}
			else {
				$page_guide .= "<td><a href='/cgi-bin/viewlog.cgi?pg=$i$mode_str'>$i</a>";
			}
		}
	}
	if ($page < $res_pages) {
		$page_guide .= "<td><a href='/cgi-bin/viewlog.cgi?pg=". ($page + 1) ."$mode_str'>Next</a>";
	}
	$page_guide .= '</table>';
}

my $query_box = '';

my $conf_code = gen_token();
$session{"confirm_code"} = $conf_code;

my $action_limit_opts = '';
my $act_cntr = 0;

for my $action_type ( sort { ${$log_action_types{$a}}{"descr"} cmp ${$log_action_types{$b}}{"descr"} } keys %log_action_types) {
	$act_cntr++;
	my $checked = '';
	if (exists $action_limit{$action_type}) {
		$checked = 'checked';
	}
	my $descrp = ${$log_action_types{$action_type}}{"descr"};
	$action_limit_opts .= qq{<INPUT type="checkbox" $checked name=action_limit_$act_cntr value="$action_type">$descrp<br>};
}

$query_box = 
qq{
<div style="width: 600px; border: 1px solid">
<form action="/cgi-bin/viewlog.cgi" method="POST">
<INPUT type="hidden" name="confirm_code" value="$conf_code">
<div id="query_feedback">
$query_feedback
</div>
<table>
<tr><td colspan="2"><LABEL style="text-decoration: underline; font-weight: bold">Limit results by</LABEL>
<tr><td><LABEL style="font-weight: bold">User</LABEL><td><INPUT type="text" value="$user_limit" name="user_limit" maxlength="40" size="30">
<tr><td><LABEL style="font-weight: bold">Date</LABEL><td><LABEL style="font-style: italic"><span style="color: red" id="from_date_error">$from_date_error</span>&nbsp;From&nbsp;</LABEL><INPUT type="text" value="$from_date_limit" name="from_date_limit" maxlength="10" size="15"><LABEL style="font-style: italic"><span style="color: red" id="to_date_error">$to_date_error</span>&nbsp;To&nbsp;</LABEL><INPUT type="text" value="$to_date_limit" name="to_date_limit" maxlength="10" size="15">
<tr><td><LABEL style="font-weight: bold">Action type</LABEL><td><DIV style="height: 100px; overflow-y: scroll; border: 1px solid">$action_limit_opts</DIV>
<tr><td colspan="2"><INPUT type="submit" name="run_query" value="Run Query">
</table>
</form>
</div>
};

my $content = 
qq{

<!DOCTYPE html>
<html lang="en">
<head>
<title>Spanj :: Exam Management Information System :: View Log of Events</title>
</head>
<body>
<iframe width="30%" height=80 frameborder="1" src="/welcome2.html">
	<h5>Welcome to the </br>Spanj Exam Management Information System</h5>
</iframe>

<iframe width="20%" height=80 frameborder="1" src="/cgi-bin/check_login.cgi?cont=/settings.html"></iframe>

<p><a href="/">Home</a> --&gt; <a href="/administrator.html">Administrator Panel</a> --&gt; <a href="/cgi-bin/viewlog.cgi">View Log of Events</a>
<hr>
<div id="pre_conf">
$per_page_guide
$query_box
<hr>
$events_table
$page_guide
</div> 
<p><a href="/">Home</a> --&gt; <a href="/administrator.html">Administrator Panel</a> --&gt; <a href="/cgi-bin/viewlog.cgi">View Log of Events</a>
</body>
</html>

};

print "Status: 200 OK\r\n";
print "Content-Type: text/html; charset=iso-8859-1\r\n";

my $len = length($content);
print "Content-Length: $len\r\n";
my @new_sess_array = ();

for my $sess_key (keys %session) {
	push @new_sess_array, $sess_key."=".$session{$sess_key};        
}

my $new_sess = join ('&',@new_sess_array);
print "X-Update-Session: $new_sess\r\n";

print "\r\n";
print $content;

sub get_intervening {
	return "" unless (@_ >= 2);
	my @days_per_month = (0, 31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31 );

	#trying to be clever
	my @days = splice(@_, 0, 2);
	my $larger  = ($days[0] cmp $days[1]) > 0 ? shift @days: pop @days;
	my $smaller = $days[0];
	my @larger_arr  = split/\-/,  $larger;
	my @smaller_arr = split/\-/, $smaller;


	my $days = 0;
	#different years
	unless ($smaller_arr[0] eq $larger_arr[0]) {

		#calculate days to end of yr

		#first count days to end of current month
	
		if ($smaller_arr[0] % 4 == 0) {
			$days_per_month[2] = 29;
		}
		else {
			$days_per_month[2] = 28;
		}
		my $days_to_end_month = $days_per_month[$smaller_arr[1]] - $smaller_arr[2];
		$days += $days_to_end_month;

		#then count months to end of yr
		#leap year
		for (my $i = $smaller_arr[1] + 1; $i < 13; $i++) {
			$days += $days_per_month[$i];	
		}

		#calculate intevening yrs;
		for (my $i = $smaller_arr[0] + 1; $i < $larger_arr[0]; $i++) {
			if ($i % 4 == 0) {
				$days += 365;
			}
			else {
				$days += 364;
			}
		}

		#reset year, month & day
		$smaller_arr[2] = 0;
		$smaller_arr[1] = 1;
		$smaller_arr[0] = $larger_arr[0];	
	}

	#different_months, same year
	unless ($smaller_arr[1] eq $larger_arr[1]) {

		#calculate days to end of current month
		my $days_to_end_month = $days_per_month[$smaller_arr[1]] - $smaller_arr[2];
		$days += $days_to_end_month;

		if ($smaller_arr[0] % 4 == 0) {#leap year
			$days_per_month[2] = 29;
		}
		else {
			$days_per_month[2] = 28;
		}
		for (my $i = $smaller_arr[1] + 1; $i < $larger_arr[1]; $i++) {
			$days += $days_per_month[$i];	
		}
		#reset month & day
		$smaller_arr[2] = 0;
		$smaller_arr[1] = $larger_arr[1];
	}

	unless ($smaller_arr[2] eq $larger_arr[2]) {
		my $days_to_larger_date = $larger_arr[2] - $smaller_arr[2];
		$days += $days_to_larger_date;
	}

	@smaller_arr = split/-/, $smaller; 
	my $day_month_yr = sprintf ("%02d/%02d/%d", $smaller_arr[2], $smaller_arr[1], $smaller_arr[0]);	

	#short-circuit to return days in-between
	#bad programming, but this' legacy code
	if (@_ and $_[0]) {
		return $days;
	}

	if ($days == 0) {
		return "Today";
	}
	elsif ($days == 1) {
		return "Yesterday";
	}
	elsif ($days < 5) {
		return "$days days ago";
	}
	#less than a month ago
	elsif ($days < 32) {
		return "$day_month_yr ($days days ago)";
	}
	#over a month, less than a day
	elsif ($days < 365) {
		my $months = int($days / 30.4);
		my $months_or_month = $months == 1 ? "month" : "months";

		my $rem_days = int($days - ($months * 30.4));
		$rem_days++;	
		my $days_or_day = $rem_days == 1 ? "day" : "days";

		return "$day_month_yr ($months $months_or_month, $rem_days $days_or_day ago)";	
	}
	#over 1 year ago
	else {
		my $yrs = int($days / 365.4);
		my $yrs_or_yr = $yrs == 1 ? "year" : "years";

		my $rem_months = int($days - ($yrs * 365));
		$rem_months++;	
		my $months_or_month = $rem_months == 1 ? "month" : "months";

		return "$day_month_yr ($yrs $yrs_or_yr, $rem_months $months_or_month ago)";
	}
}

sub htmlspecialchars {
	my $cp = $_[0];
	$cp =~ s/&/&#38;/g;
        $cp =~ s/</&#60;/g;
        $cp =~ s/>/&#62;/g;
        $cp =~ s/'/&#39;/g;
        $cp =~ s/"/&#34;/g;
        return $cp;
}


sub gen_token {
	my @key_space = ("A","B","C","D","E","F","0","1","2","3","4","5","6","7","8","9");
	my $len = 5 + int(rand 15);
	if (@_ and ($_[0] eq "1")) {
		@key_space = ("A","B","C","D","E","F","G","H","J","K","L","M","N","P","T","W","X","Z","7","0","1","2","3","4","5","6","7","8","9");
		$len = 10 + int (rand 5);
	}
	my $token = "";
	for (my $i = 0; $i < $len; $i++) {
		$token .= $key_space[int(rand @key_space)];
	}
	return $token;
}

sub get_intervening_list {

	my @days_per_month = (0, 31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31 );

	my $dy_cnt = get_intervening($_[0], $_[1], 1);

	my $start = $_[0];
	my @bts = split/-/, $start;

	my %lst = ();
	$lst{sprintf("%d-%02d-%02d", $bts[0], $bts[1], $bts[2])} = 1;

	for (my $i = 0; $i < $dy_cnt; $i++) {
		#month over
		if (++$bts[2] > $days_per_month[$bts[1]]) {
			$bts[2] = 1;

			#increment month
			$bts[1]++;

			#increment year, cycle to Jan;
			if ($bts[1] > 12) {
				$bts[0]++;
				$bts[1] = 1;
				if ($bts[0] % 4 == 0) {
					$days_per_month[2] = 29;
				}
				else {
					$days_per_month[2] = 28;
				}
			}
		}
		$lst{sprintf("%d-%02d-%02d", $bts[0], $bts[1], $bts[2])} = 1;
	}	
	return %lst;
}
