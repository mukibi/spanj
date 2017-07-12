#!/usr/bin/perl

use strict;
use warnings;
use feature "switch";
 
use CGI;
use DBI;
use Fcntl qw/:flock SEEK_END/;
require "./conf.pl";

our($db,$db_user,$db_pwd,$log_d);
my $authd = 0;
my %session;
my $page = 1;
my $per_page = 10;
my %auth_params;
my $con;
my @expired = ();
my @all_tokens = ();
my $search_str = "";
my $search_mode = 0;
my $mode_str = "";
my $add_token_feedback = "";

#only admin can manage tokens
#well, the admin and anyone
#else with the admin password
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
	if (exists $session{"id"} and $session{"id"} eq "1") {
		$authd++;
	}
	if (exists $session{"mng_per_page"} and $session{"mng_per_page"} =~ /^(\d+)$/) {
		$per_page = $1;
	}
}

if ($authd) {

	if ( exists $ENV{"QUERY_STRING"} ) {
		if ( $ENV{"QUERY_STRING"} =~ /\&?pg=(\d+)\&?/ ) {	
			$page = $1;
		}

		if ( $ENV{"QUERY_STRING"} =~ /\&?per_page=(\d+)\&?/ ) {
			
			my $possib_per_page = $1;
			
			if (($possib_per_page % 10) == 0) { 	
				$per_page = $possib_per_page;
			}
			else {
				if ($possib_per_page < 10) {	
					$per_page = 10;
				}
				else {
					$per_page = substr("".$possib_per_page, 0, -1) . "0";
				}	
			}
			#when the user changes the results per
			#page to more results per page, they should
			#be sent a page down.
			#if they select fewer results per page, they should
			#be sent a page up.
			$session{"mng_per_page"} = $per_page;
		}

		if ( $ENV{"QUERY_STRING"} =~ /\&?mode=search\&?/i ) {
			$search_mode++;
			$mode_str = "&mode=search";	
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

	my $order_by_clause = "ORDER BY expiry DESC";
	#most recent ORDER BY statement should take precedence over
	#previous ORDER BYs
	my ($order_by, $sort_order);

	if (exists $auth_params{"sort_by"} ) {
		#Request will result in re-ordering of results
		#Therefore, jumps to page 1
		if (exists $session{"mng_sort_by"} and ($session{"mng_sort_by"} ne $auth_params{"sort_by"})) {
			$page = 1;
		}

		if (exists $session{"mng_sort_order"} and ($session{"mng_sort_order"} ne $auth_params{"sort_order"})) {
			$page = 1;
		}
	
		$order_by = lc($auth_params{"sort_by"});	
		my $user_ordered = 0;

		given ($order_by) {
			when ("issued_to") {$user_ordered++;$order_by_clause = "ORDER BY issued_to"}
			when ("expiry") {$user_ordered++;$order_by_clause = "ORDER BY expiry"}
			when ("privileges") {$user_ordered++;$order_by_clause = "ORDER BY count_str(privileges, ',')"}
		}

		if ($user_ordered) {
			$session{"mng_sort_by"} = $order_by;	
			my $valid_sort_order = 0;
			if (exists $auth_params{"sort_order"}) {
				$sort_order = $auth_params{"sort_order"};
				given ($sort_order) {
					when ("0") {$valid_sort_order++; $order_by_clause .= " DESC"}
					when ("1") { $valid_sort_order++; $order_by_clause .= " ASC"}
				}
			}
			unless ($valid_sort_order) {
				$order_by_clause .= " DESC"; 	
			}
			else {	
				$session{"mng_sort_order"} = $sort_order;
			}
		}
	}

	elsif (exists $session{"mng_sort_by"} ) {
		$order_by = lc($session{"mng_sort_by"});		
		my $user_ordered = 0;

		given ($order_by) {
			when ("issued_to") {$user_ordered++;$order_by_clause = "ORDER BY issued_to"}
			when ("expiry") {$user_ordered++;$order_by_clause = "ORDER BY expiry"}
			when ("privileges") {$user_ordered++;$order_by_clause = "ORDER BY count_str(privileges, ',')"}
		}
		if ($user_ordered) {
			my $sort_order;
			my $valid_sort_order = 0;
			if (exists $session{"mng_sort_order"}) {
				$sort_order = $session{"mng_sort_order"};	
				given ($sort_order) {
					when ("0") {$valid_sort_order++; $order_by_clause .= " DESC"}
					when ("1") { $valid_sort_order++; $order_by_clause .= " ASC"}
				}
			}
			unless ($valid_sort_order) {
				$order_by_clause .= " DESC"; 
			}
		}
	}

	my $name_match_clause = "";
	
	if ($search_mode) { 
		if ( exists $auth_params{"search"} ) {
			if (exists $auth_params{"confirm_code"} and exists $session{"confirm_code"}) {
				if ($auth_params{"confirm_code"} eq $session{"confirm_code"}) {	
					$name_match_clause = "WHERE issued_to LIKE ? ";	
					$session{"search"} = $auth_params{"search"};
					$search_str = $auth_params{"search"};
				}
				else {
					$search_mode = 0;
				}
			}
			else {
				$search_mode = 0;
			}
		}

		elsif (exists $session{"search"}) {	
			$name_match_clause = "WHERE issued_to LIKE ? ";
			$search_str = $session{"search"};
		}
		#No search term in POSTed data or session
		#Just clear the search mode flag
		else {
			$search_mode = 0;
			$mode_str = "";
		}
	}

	my $row_count =	0;

	if ($search_mode) {
			$con = DBI->connect("DBI:mysql:database=$db;host=localhost", $db_user, $db_pwd, {'RaiseError'=>1, 'AutoCommit'=> 0});		
			if ($con) {
				my $prep_stmt2 = $con->prepare("SELECT count(value) FROM tokens WHERE issued_to LIKE ? LIMIT 1");
				if ($prep_stmt2) {
					my $rc2 = $prep_stmt2->execute("%".$search_str."%");
					if ($rc2) {
						my @rslts = $prep_stmt2->fetchrow_array();
						if (@rslts) {	
							$row_count = $rslts[0];
						}
					}
					else {
						print STDERR "Could not execute SELECT FROM tokens: ", $prep_stmt2->errstr, $/;
					}
				}
				else {
					print STDERR "Could not prepare SELECT FROM tokens: ", $prep_stmt2->errstr, $/;  
				}
			}
			else {
				print STDERR "Cannot connect: $con->strerr$/";
			}	
	}
	else {
  		$con = DBI->connect("DBI:mysql:database=$db;host=localhost", $db_user, $db_pwd, {'RaiseError'=>1, 'AutoCommit'=> 0});		
		if ($con) {
			my $prep_stmt2 = $con->prepare("SELECT count(value) FROM tokens LIMIT 1");
			if ($prep_stmt2) {
				my $rc2 = $prep_stmt2->execute();
				if ($rc2) {
					my @rslts = $prep_stmt2->fetchrow_array();
					if (@rslts) {
						$row_count = $rslts[0];
					}
				}
				else {
					print STDERR "Could not execute SELECT FROM tokens: ", $prep_stmt2->errstr, $/;
				}
			}
			else {
				print STDERR "Could not prepare SELECT FROM tokens: ", $prep_stmt2->errstr, $/;  
			}
		}
		else {
			print STDERR "Cannot connect: $con->strerr$/";
		}
	
	}

	my $res_pages = 1;
	#simple logic
	#if the remaining results ($row_count - x) overflow the current page (x = $page * $per_page)
	#and you are on page 1 then this' a multi_page setup

	$res_pages = $row_count / $per_page;
	if ($res_pages > 1) {
		if (int($res_pages) < $res_pages) {
			$res_pages = int($res_pages) + 1;
		}
	}
	my $page_guide = '';

	if ($res_pages > 1) {
		$page_guide .= '<table cellspacing="50%"><tr>';

		if ($page > 1) {
			$page_guide .= "<td><a href='/cgi-bin/managetokens.cgi?pg=".($page - 1) . $mode_str ."'>Prev</a>";
		}

		if ($page < 10) {
			for (my $i = 1; $i <= $res_pages and $i < 11; $i++) {
				if ($i == $page) {
					$page_guide .= "<td><span style='font-weight: bold'>$i</span>";
				}
				else {
					$page_guide .= "<td><a href='/cgi-bin/managetokens.cgi?pg=$i$mode_str'>$i</a>";
				}
			}
		}
		else {
			for (my $i = $page - 4; $i <= $res_pages and $i < ($page + 4); $i++) {
				if ($i == $page) {
					$page_guide .= "<td><span style='font-weight: bold'>$i</span>";
				}
				else {
					$page_guide .= "<td><a href='/cgi-bin/managetokens.cgi?pg=$i$mode_str'>$i</a>";
				}
			}
		}
		if ($page < $res_pages) {
			$page_guide .= "<td><a href='/cgi-bin/managetokens.cgi?pg=".($page + 1).$mode_str."'>Next</a>";
		}
		$page_guide .= '</table>';
	}

	my $per_page_guide = '';

	if ($row_count > 10) {
		$per_page_guide .= "<p><em>Results per page</em>: <span style='word-spacing: 1em'>";
		for my $row_cnt (10, 20, 50, 100) {
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
				$per_page_guide .= " <a href='/cgi-bin/managetokens.cgi?pg=$re_ordered_page&per_page=$row_cnt$mode_str'>$row_cnt</a>";
			}
		}
		$per_page_guide .= "</span>";
	}

	my $current_tokens = "";
	my $cntr = 0;	
	unless ($con) {
		$con = DBI->connect("DBI:mysql:database=$db;host=localhost", $db_user, $db_pwd, {'RaiseError'=>1, 'AutoCommit'=> 0});		
	}
	if ($con) {
		if (exists $auth_params{"del_expired"}) {
			if ($auth_params{"confirm_code"} eq $session{"confirm_code"}) {	
				my $del_count = 0;
				my @to_del;
				my @to_del_stmt_bts;
				my $time = time;
				for my $param (keys %auth_params) {
					if ($param =~ /^expired_/) {
						$del_count++;
						push @to_del, $auth_params{$param};
						push @to_del_stmt_bts, "(value=? AND expiry < $time)";
					}
				}
				if ($del_count > 0) {
				
					my $del_clause = join (' OR ', @to_del_stmt_bts);
					my $del_stmt = "DELETE FROM tokens WHERE $del_clause LIMIT $del_count";
					my $prep_stmt0 = $con->prepare($del_stmt);
					if ($prep_stmt0) {
						my $rc = $prep_stmt0->execute(@to_del);	
						if ($rc) {
							$con->commit();	
						}
						else {
							print STDERR "Could not execute DELETE FROM tokens: ", $prep_stmt0->errstr, $/;
						}
					}
					else {
						print STDERR "Could not prepare DELETE FROM tokens: ", $prep_stmt0->errstr, $/;  
					}
						
					my @today = localtime;	
					my $day_month_yr = sprintf "%d-%02d-%02d", $today[5] + 1900, $today[4] + 1, $today[3];
					open (my $log_f, ">>$log_d/user_actions-$day_month_yr.log");
        				if ($log_f) {
                				@today = localtime;
						my $time = sprintf "%d-%02d-%02d-%02d%02d.%02d", $today[5]+1900,$today[4]+1,$today[3],$today[2],$today[1],$today[0];
						flock($log_f, LOCK_EX) or print STDERR "Could not log delete token due to flock issue: $!$/";
						seek($log_f, 0, SEEK_END);
						for my $del (@to_del) {
                					print $log_f $session{"id"}, " DELETE TOKEN $del $time\n";
						}
						flock ($log_f, LOCK_UN);
                				close $log_f;
        				}
					else {
						print STDERR "Could not log DELETE TOKEN $session{'id'}: $!\n";
					}
				}
			}
		}
		elsif (exists $auth_params{"delete"}) {
			if ($auth_params{"confirm_code"} eq $session{"confirm_code"}) {	
				my $del_count = 0;
				my @to_del;
				my @to_del_stmt_bts;
				my $time = time;
				for my $param (keys %auth_params) {
					if ($param =~ /^delete_/) {
						$del_count++;
						push @to_del, $auth_params{$param};
						push @to_del_stmt_bts, "value=?";
					}
				}
				if ($del_count > 0) {
				
					my $del_clause = join (' OR ', @to_del_stmt_bts);					
					my $prep_stmt0 = $con->prepare("DELETE FROM tokens WHERE $del_clause LIMIT $del_count");

					if ($prep_stmt0) {
						my $rc = $prep_stmt0->execute(@to_del);	
						if ($rc) {
							$con->commit();	
						}
						else {
							print STDERR "Could not execute DELETE FROM tokens: ", $prep_stmt0->errstr, $/;
						}
					}
					else {
						print STDERR "Could not prepare DELETE FROM tokens: ", $prep_stmt0->errstr, $/;  
					}
						
					my @today = localtime;	
					my $day_month_yr = sprintf "%d-%02d-%02d", $today[5] + 1900, $today[4] + 1, $today[3];

					open (my $log_f, ">>$log_d/user_actions-$day_month_yr.log");
        				if ($log_f) {
                				@today = localtime;
						my $time = sprintf "%d-%02d-%02d-%02d%02d.%02d", $today[5]+1900,$today[4]+1,$today[3],$today[2],$today[1],$today[0];
						flock ($log_f, LOCK_EX);
						seek($log_f, 0, SEEK_END);
						for my $del (@to_del) {
							print $log_f $session{"id"}, " DELETE TOKEN $del $time\n";	
						}
						flock($log_f, LOCK_UN);
                				close $log_f;
        				}
					else {
						print STDERR "Could not log DELETE TOKEN  $session{'id'}: $!\n";
					}
				}
			}
		}

		elsif (exists $auth_params{"extend"}) {
			if ($auth_params{"confirm_code"} eq $session{"confirm_code"}) {	
				my $time = time;
				my %to_update = ();	
				my $update_cnt = 0;
				my $expiry_days = 1;
				for my $param (keys %auth_params) {
					if ($param =~ /^extend_(.+)$/) {
						my $token = $1;
						my $new_expiry = $time + (24*60*60);
						if ($auth_params{$param} =~ /^([1-3])$/) {
							$expiry_days = $1;
							$new_expiry = $time + ($expiry_days * 24 * 60 * 60);	
						}
						$to_update{$token} = $new_expiry;
						$update_cnt++;	
					}
				}

				if ($update_cnt) {
					
					my $prep_stmt0 = $con->prepare("UPDATE tokens SET expiry=? WHERE value=? LIMIT 1");
					if ($prep_stmt0) {
						for my $tok (keys %to_update) {
							my $rc = $prep_stmt0->execute($to_update{$tok}, $tok);	
							unless($rc) {
								print STDERR "Could not execute UPDATE tokens: ", $prep_stmt0->errstr, $/;
							}
						}
						$con->commit();
					}
					else {
						print STDERR "Could not prepare UPDATE tokens: ", $prep_stmt0->errstr, $/;  
					}

					my @today = localtime;
					my $day_month_yr = sprintf "%d-%02d-%02d", $today[5] + 1900, $today[4] + 1, $today[3];
					open (my $log_f, ">>$log_d/user_actions-$day_month_yr.log");
        				if ($log_f) {
                				@today = localtime;
						my $log_time = sprintf "%d-%02d-%02d-%02d%02d.%02d", $today[5]+1900,$today[4]+1,$today[3],$today[2],$today[1],$today[0];
						flock($log_f, LOCK_EX) or print STDERR "Could not log extend lease due to flock error: $!$/";
						seek($log_f, 0, SEEK_END);
						for my $update_tok (keys %to_update) {	
							my $expires_in_days = $to_update{$update_tok} - $time;
							$expires_in_days = $expires_in_days/(24*60*60);	
                					print $log_f "1 EXTEND LEASE ($update_tok,$expires_in_days days) $log_time\n";	
						}
						flock ($log_f, LOCK_UN);
                				close $log_f;
        				}
					else {
						print STDERR "Could not log EXTEND LEASE $session{'id'}: $!\n";
					}
				}
			}
		}	

		if (exists $auth_params{"add_new"}) {
			if ( (exists $auth_params{"confirm_code"} and exists $session{"confirm_code"}) and ($auth_params{"confirm_code"} eq $session{"confirm_code"})  ) {	  

				my @privs;

				push @privs,"CSR(*)" if (exists $auth_params{"csr"});

				for my $priv_str ("esr", "cm", "em", "vm", "grc") {
					if (exists $auth_params{$priv_str}) {
						my @class_bts = split/,/,$auth_params{$priv_str};
						for my $class_bt (@class_bts) {
							push @privs, uc($priv_str) . "($class_bt)";
						}
					}
				}
	
				my $valid = 1;
				my @errors;
				my $privs_str;

				unless (@privs) {
					push @errors, "You have not specified the privileges of this token";
					$valid = 0;
				}
				else {
 					$privs_str = join(',', @privs);
				}
				my $issued_to;				
				if (exists $auth_params{"issued_to"}) {
					$issued_to = $auth_params{"issued_to"};
					unless ($issued_to =~ /^[A-Za-z\'\-\s]+$/) {
						push @errors, "Invalid characters in the 'issued to' field. Only letters of the alphabet and a few punctuation marks are allowed(', -)";
						$valid = 0;
					}
				}
				else {
					push @errors, "You have not specified the name of the person to whom this token is issued";
					$valid = 0;
				}
				my $expiry;
				if (exists $auth_params{"expires_in"}) {
					$expiry =  $auth_params{"expires_in"};	
					unless ($expiry =~ /^[1-3]$/) {
						push @errors, "Invalid expiry time. Valid expiry time is 1,2 or 3 day(s)";
						$valid = 0;	
					}
					else {
						$expiry = time + ($expiry * 24*60*60); 
					}
				}
				else {
					push @errors, "You have not specified the duration of this token's life";
					$valid = 0;				
				}
				if ($valid) {
					#to avoid the (improbable) problem of duplicate tokens
					#generate 5 potential tokens, search DB for
					#the 5, remove any that are found
					#use the mod
					my %possib_toks;
					foreach (0..4) {
						$possib_toks{gen_token(1)}++;
					}
					my $prep_stmt0 = $con->prepare("SELECT value FROM tokens WHERE value=? OR value=? OR value=? OR value=? OR value=? LIMIT 5");
					if ($prep_stmt0) {
						my $rc = $prep_stmt0->execute(keys %possib_toks);
						if ($rc) {
							while (my @valid = $prep_stmt0->fetchrow_array()) {
								delete $possib_toks{$valid[0]};			
							}
						}
						else {
							print STDERR "Could not execute SELECT FROM tokens: ", $prep_stmt0->errstr, $/;
						}
					}
					else {
						print STDERR "Could not prepare SELECT FROM tokens: ", $prep_stmt0->errstr,$/;  
					}

					my $prep_stmt1 = $con->prepare("INSERT INTO tokens VALUES(?,?,?,?)");
					my $tok_to_use = (keys %possib_toks)[0];

					my $rc = $prep_stmt1->execute($tok_to_use, $expiry, $issued_to, $privs_str);

					if ($rc) {	
						$con->commit();

						my @today = localtime;	
						my $day_month_yr = sprintf "%d-%02d-%02d", $today[5] + 1900, $today[4] + 1, $today[3];
						open (my $log_f, ">>$log_d/user_actions-$day_month_yr.log");
        					if ($log_f) {
                					@today = localtime;
							my $time = sprintf "%d-%02d-%02d-%02d%02d.%02d", $today[5]+1900,$today[4]+1,$today[3],$today[2],$today[1],$today[0];		
							flock($log_f, LOCK_EX) or print STDERR "Could not log add token due to flock error: $!$/";
							seek($log_f, 0, SEEK_END);
	           					print $log_f $session{"id"}, " ADD TOKEN ($tok_to_use, $expiry, $issued_to, $privs_str) $time\n";
							flock($log_f, LOCK_UN);
                					close $log_f;
        					}
						else {
							print STDERR "Could not log EXTEND LEASE $session{'id'}: $!\n";
						}
						$add_token_feedback = qq{<em>Token <span style="font-decoration: underline; font-weight: bold">$tok_to_use</span> issued to <span style="font-decoration: underline; font-weight: bold">$issued_to</span> has been successfully added to the system!</em>};
					}
					else {
						print STDERR "Could not execute INSERT INTO tokens: ", $prep_stmt1->errstr, $/;
					}				
				}
				else {
					$add_token_feedback = qq{<span style="color: red">Token not added!</span>The following issues were found with the request:<ol>};
					foreach (@errors) {
						$add_token_feedback .= "<li>" . $_; 
					}
					$add_token_feedback .= "</ol>";
				}
			}
		}

		my $limit_clause = ""; 	

		if ($res_pages > 1) {
			my $offset = 0;
			if (exists $session{"mng_per_page"}) {
				$offset = $session{"mng_per_page"} * ($page - 1);	
				$limit_clause = " LIMIT $offset,".$session{"mng_per_page"};
			}
			else {
				$offset = $per_page * ($page - 1);  
				$limit_clause = " LIMIT $offset,$per_page";
			}
		}
		
		my $prep_stmt = $con->prepare("SELECT value,expiry,issued_to,privileges FROM tokens $name_match_clause$order_by_clause$limit_clause");
					
		if ($prep_stmt) {
			my $rc;
			if ($search_mode) {
				$rc = $prep_stmt->execute("%".$search_str. "%");
			}
			else {
				$rc = $prep_stmt->execute();
			}	

			if ($rc) {
				while (my @valid = $prep_stmt->fetchrow_array()) {
					push @all_tokens, "{token:\"$valid[0]\", issued_to:\"$valid[2]\"}";

					my $expired = 0;
					my $human_time = "";
					my $secs_to_expiry = $valid[1] - time;

					if ($secs_to_expiry <= 0) {
						$expired++;
						$human_time = "EXPIRED";
						push @expired, "{token:\"$valid[0]\", issued_to:\"$valid[2]\"}";
					}
			
					else {
						my $days = $secs_to_expiry / (60*60*24);
						if ($days >= 1) {
							if (int($days) == 1) {
								$human_time .= int($days) . "day ";
							}
							else {
								$human_time .= int($days) . "days ";
							}
						}

						$secs_to_expiry -= int($days) * (60*60*24);
						my $hrs = $secs_to_expiry / (60*60);
						if ($hrs >= 1 or $days >= 1) {
							if (int($hrs) == 1) {
								$human_time .= int($hrs) . "hr ";
							}
							else {
								$human_time .= int($hrs) . "hrs ";
							}
						}
						$secs_to_expiry -= int($hrs) * (60*60);

						my $mins = $secs_to_expiry / 60;
						$human_time .= int($mins) . "min ";
					}

					my $human_readable_privs = $valid[3];
					$human_readable_privs =~ s/CSR/Create Student Roll/g;
					$human_readable_privs =~ s/ESR/Edit Student Roll/g;
					$human_readable_privs =~ s/CM/Create Marksheet/g;
					$human_readable_privs =~ s/EM/Edit Marksheet/g;
					$human_readable_privs =~ s/VM/View Marksheet/g;
					$human_readable_privs =~ s/GRC/Generate Report Cards/g;
					my @privs = split/,/,$human_readable_privs;
					my $priv_list = join('<br>', @privs);

					$cntr++;
					if ($expired) {
						$current_tokens .= "<tr style='color: grey'><td><input type='checkbox' name='$valid[0]' id='$valid[0]' onclick=\"check_token('$valid[0]','$valid[2]')\"><td>$valid[0]<td>$human_time<td>$valid[2]<td>$priv_list";

					}
					else {
						$current_tokens .= "<tr><td><input type='checkbox' name='$valid[0]' id='$valid[0]' onclick=\"check_token('$valid[0]','$valid[2]')\"><td>$valid[0]<td>$human_time<td>$valid[2]<td>$priv_list";
					}
				}
				#$prep_stmt->finish();
			}
			else {
				print STDERR "Could not execute SELECT FROM tokens: ", $prep_stmt->errstr, $/;
			}	
		}
		else {
			print STDERR "Could not prepare SELECT FROM tokens: ", $prep_stmt->errstr, $/;  
		}
	}

	my $tokens_table;
	if ($cntr == 0) {
		if ($search_mode) {
			$tokens_table = '<span style="color: red">Your search \'' . htmlspecialchars($search_str) . '\' did not match any tokens in the system.</span>'; 
		}
		else {
			$tokens_table = '<em>No tokens to display.</em><br>';
		}
	}

	else {
		$tokens_table = '<table border="1" cellpadding="5%"><thead><th><input type="checkbox" title="Select all on page" name="select_all" id="select_all" onclick="check_all()"><th>Token<th>Expiry<th>Issued to<th>Privileges</thead>';
		$tokens_table .= '<tbody>' . $current_tokens. '</tbody></table>';
	}
	my $expired_tokens = '[]';
	my $all_tokens_var = '[]';
	my $conf_code = gen_token();
	$session{"confirm_code"} = $conf_code;

	if (@expired) {
 		$expired_tokens = '[' . join (', ', @expired) . ']';	
	}
	if ($cntr) {
		$all_tokens_var = '[' . join(', ', @all_tokens) . ']';
	}

	my $sort_guide = '';	
	if ($cntr > 0) { 
		$sort_guide = 
	'<P>
	<form method="POST" action="/cgi-bin/managetokens.cgi?pg='. $page .$mode_str .'"> 
	<table cellpadding="5%">
	<tr>
	<td><label for="sort_by">Sort by</label>
	<td><select name="sort_by" id="sort_by" onchange="customize_sort_description()">';	

		my $sort_by = "expiry";

		if (exists $session{"mng_sort_by"}) {
			$sort_by = $session{"mng_sort_by"};
		}

		#probably tired
		for (my $i = 0; $i < 3; $i++) {
			if ($i == 0) {
				if ($sort_by eq "issued_to") {
					$sort_guide .= '<option selected value="issued_to">Issued to</option>'
				}
				else {
					$sort_guide .= '<option value="issued_to">Issued to</option>'
				}
			}
			elsif ($i == 1) {
				if ($sort_by eq "expiry") {
					$sort_guide .= '<option selected value="expiry">Expiry time</option>'
				}
				else {
					$sort_guide .= '<option value="expiry">Expiry time</option>'
				}
			}
			else {
				if ($sort_by eq "privileges") {
					$sort_guide .= '<option selected value="privileges">Number of privileges</option>'
				}
				else {
					$sort_guide .= '<option value="privileges">Number of privileges</option>'
				}	
			}
		}

		$sort_guide .=

	'</select>
	<td><label for="sort_order">Sort order</label>
	<td>
	<span id="sort_order_container">';

		my $sort_order = "0";

		if (exists $session{"mng_sort_order"}) {
			$sort_order = $session{"mng_sort_order"};
		}

		#outrageous code
		#certainly the reason I'll never work @ Google 
	
		#sort by issued_to
		if ($sort_by eq "issued_to") {
				#sort ascending 
				if ($sort_order eq "0") {
					$sort_guide .= 
					'<SELECT name="sort_order">
						<OPTION selected value="0">Alphabetical order(Z-A)</OPTION>
						<OPTION value="1">Alphabetical order(A-Z)</OPTION>
					</SELECT>';
				}
				#sort descending
				else {
					$sort_guide .= 
					'<SELECT name="sort_order">
						<OPTION value="0">Alphabetical order(Z-A)</OPTION>
						<OPTION selected value="1">Alphabetical order(A-Z)</OPTION>
					</SELECT>';
				}	
		}
		#sort by expiry
		elsif ($sort_by eq "expiry") {
				#sort ascending
				if ($sort_order eq "0") {
					$sort_guide .=
 					'<SELECT name="sort_order">"
						<OPTION selected value="0">Farthest from expiry first</OPTION>
						<OPTION value="1">Closest to expiry first</OPTION>
					 </SELECT>';
				}
				#sort descending
				else {
					$sort_guide .=
  					'<SELECT name="sort_order">"
						<OPTION value="0">Farthest from expiry first</OPTION>
						<OPTION selected value="1">Closest to expiry first</OPTION>
					 </SELECT>';
				}
		}
		#sort by privileges
		else {
				#sort ascending
				if ($sort_order eq "0") {
					$sort_guide .=
 					'<SELECT name="sort_order">
						<OPTION selected value="0">Most - least privileges</OPTION>
						<OPTION value="1">Least - most privileges</OPTION>
					</SELECT>';
				}
				#sort descending
				else {
					$sort_guide .= 
 					'<SELECT name="sort_order">
						<OPTION value="0">Most - least privileges</OPTION>
						<OPTION selected value="1">Least - most privileges</OPTION>
					</SELECT>';
				}
		}
		
		$sort_guide .= 
	'</span>
	<td><input type="submit" name="sort" value="Sort">	
	</table>
	</form>
	';
	}
	my $search_bar = 
	'<form action="/cgi-bin/managetokens.cgi?pg=1&mode=search" method="POST">
	<table cellpadding="10%">
	<tr>
	<td><input type="text" size="30" maxlength="50" name="search" value="'.$search_str.'">
	<td><input type="submit" name="search_go" value="Search" title="Search">
	<input type="hidden" name="confirm_code" value="'.$conf_code .'">
	</table>
	</form>
	';

	my @today = localtime;
	my $current_yr = $today[5] + 1900;
	my $yrs_study = 4;

	my %class_teachers = ();

	my @classes = ("1", "2", "3", "4");
	my @subjects = ("Mathematics", "English", "Kiswahili", "History", "CRE", "Geography", "Physics", "Chemistry", "Biology", "Computers", "Business Studies", "Home Science");
	
	if ($con) {
		#ORDER DESC to ensure 'classes' will be loaded when 
		#'class teacher%' vals r processed.

		my $prep_stmt0 = $con->prepare("SELECT name, value FROM vars WHERE owner='1' AND (name='classes' OR name='subjects' OR name LIKE 'class teacher%') ORDER BY name DESC");
		if ($prep_stmt0) {
			my $rc = $prep_stmt0->execute();	
			if ($rc) {
				my %class_subjects;

				while ( my @valid = $prep_stmt0->fetchrow_array() ) {

					if ( $valid[0] =~ /^class\steacher\s([^\(]+)\((\d{4,})\)$/ ) {

						my $class = $1;
						my $year = $2;

						my $class_yr = 1;
						if ($class =~ /(\d+)/) {
							$class_yr = $1; 
						}

						my $class_now = ($current_yr - $year) + $class_yr; 
						$class =~ s/\d+/$class_now/;

						#want to guarantee case-insensitivity
						#by making the entries in 'class teacher'
						#look like 'classes'
						foreach ( @classes ) {
							if ( lc($_) eq lc($class) ) {
								$class = $_;
								last;
							}
						}

						#let's hope the admin distinguishes different
						$class_teachers{ lc($valid[1]) } = $class;

					}
					else {
						$class_subjects{$valid[0]} = $valid[1];

						if ($valid[0] eq lc("classes")) {

							my ( $min_class, $max_class ) = ( undef,undef );
							@classes  =  split/,\s*/, $valid[1];

							foreach (@classes) {

								if ($_ =~ /(\d+)/) {

									my $tst_yr = $1;
									if (not defined $min_class) {
										$min_class = $tst_yr;
										$max_class = $tst_yr;
									}
									else {
										$min_class = $tst_yr if ($tst_yr < $min_class);
										$max_class = $tst_yr if ($tst_yr > $max_class);
									}

								}
								$yrs_study = ($max_class - $min_class) + 1;
							}
						}
					}
				}

				#Save the default classes and subjects to the server
				my $set_defaults = 0;
				my $set_defaults_clause = ""; 
				my @set_defaults_params = ();
				unless (exists $class_subjects{"classes"}) {
					$set_defaults_clause .= "INSERT INTO vars VALUES (?, ?, ?, ?)";
					push @set_defaults_params, ("1","classes", join(',', @classes), "1-classes");
					$set_defaults++;
				}
				unless (exists $class_subjects{"subjects"}) {
					if ($set_defaults) {
						$set_defaults_clause .= ", (?, ?, ?, ?)";
					}
					else {
						$set_defaults_clause .= "INSERT INTO vars VALUES (?, ?, ?, ?)";
					}
					push @set_defaults_params, ("1","subjects", join(',', @subjects), "1-subjects");
					$set_defaults++;
				}
				if ($set_defaults) {
					my $prep_stmt1 = $con->prepare($set_defaults_clause);
					if ($prep_stmt1) {
						my $rc = $prep_stmt1->execute(@set_defaults_params);
						if ($rc) {
							$con->commit();
							my @today = localtime;	
							my $day_month_yr = sprintf "%d-%02d-%02d", $today[5] + 1900, $today[4] + 1, $today[3];
							open (my $log_f, ">>$log_d/user_actions-$day_month_yr.log");
        						if ($log_f) {
                						@today = localtime;
								my $time = sprintf "%d-%02d-%02d-%02d%02d.%02d", $today[5]+1900,$today[4]+1,$today[3],$today[2],$today[1],$today[0];
								flock ($log_f, LOCK_EX) or print STDERR "Could not log add sysvars due to flock error: $!$/";
								seek ($log_f, 0, SEEK_END);
								for my $reset_default (@set_defaults_params) {
									my $log_msg = join(', ', ("1","subjects", join(',', @subjects), "1-subjects"));
                							print $log_f "$session{'id'} ADD SYSVARS $log_msg $time\n";
								}
								flock ($log_f, LOCK_UN);
                						close $log_f;
        						}
							else {
								print STDERR "Could not log ADD SYSVARS $session{'id'}: $!\n";
							}
						}
						else {
							print STDERR "Could not execute INSERT INTO vars: ", $prep_stmt1->errstr, $/;
						}
					}
					else {
						print STDERR "Could not execute INSERT INTO vars: ", $prep_stmt1->errstr, $/;
					}
					$con->commit();
				}	
				@classes  =  split/,\s*/, $class_subjects{"classes"};
	
			@subjects = split/,\s*/, $class_subjects{"subjects"};
			}
			else {
				print STDERR "Could not execute SELECT FROM vars: ", $prep_stmt0->errstr, $/;
			}
		}
		else {
			print STDERR "Could not prepare SELECT FROM vars: ", $prep_stmt0->errstr,$/;  
		}		
	}

	#read list of teachers
	
	my %teachers = ();

	if ($con) {
		my $prep_stmt3 = $con->prepare("SELECT id,name,subjects FROM teachers");
		if ($prep_stmt3) {
			my $rc = $prep_stmt3->execute();
			if ($rc) {
				while (my @rslts = $prep_stmt3->fetchrow_array()) {

					my $machine_class_subjs = $rslts[2];

					#now i have 
					#[0]: English[1A(2016),2A(2015)]
					#[1]: Kiswahili[3A(2014)]
					my @subj_groups = split/;/, $machine_class_subjs;	
					my @permissions = ();

					#take English[1A(2016),2A(2015)]
					for my $subj_group (@subj_groups) {

						my ($subj,$classes_str);
					
						if ($subj_group =~ /^([^\[]+)\[([^\]]+)\]$/) {
							#English
							my $subj = $1;
							#1A(2016),2A(2015)
							my $classes_str = $2;	
							#[0]: 1A(2016)
							#[1]: 2A(2015)
							my @classes_list = split/,/, $classes_str;
							my @reformd_classes_list = ();

							#take 1A(2016) 	
							for my $class (@classes_list) {

								if ( $class =~ /\((\d+)\)$/ ) {

									my $grad_yr = $1;	

									my $class_dup = $class;
									$class_dup =~ s/\($grad_yr\)//;

									if ($grad_yr >= $current_yr) {
										my $class_yr = $yrs_study - ($grad_yr - $current_yr);
										$class_dup =~ s/\d+/$class_yr/;
										push @permissions, "em_${subj}_${class_dup}";
										push @permissions, "cm_${subj}_${class_dup}";	
									}
								}
							}
						}
					}

					#is this teacher a class teacher.
					if ( exists $class_teachers{ lc($rslts[1]) } ) {

						my $class = $class_teachers{ lc($rslts[1]) };
						push @permissions, ("vm_$class", "grc_$class", "esr_$class");

					}

					my $permissions_str = join(",", @permissions);
					$teachers{$rslts[0]} = { "name" => $rslts[1], "permissions" => $permissions_str };
				}
			}
			else {
				print STDERR "Could not execute SELECT FROM teachers: ", $prep_stmt3->errstr, $/;
			}
		}
		else {
			print STDERR "Could not prepare SELECT FROM teachers: ", $prep_stmt3->errstr, $/;
		}
	}


	$con->disconnect();

	#simple text field
	my $issued_to_field = qq!'<TD><LABEL for="issued_to" style="font-weight: bold"><span id="issued_to_asterisk" style="color: red"></span>Issued to</LABEL><TD><INPUT type="text" size="25" maxlength="32" name="issued_to" value="" id="issued_to" onchange="issued_to_changed()">'!;

	
	my @tas_js_hash_bts = ();

	#fancy combobox
	if (keys %teachers) {
		my $options = "";
		foreach (keys %teachers) {
			my $ta_name = $teachers{$_}->{"name"};
			$options .= qq{<OPTION value="$ta_name">$ta_name</OPTION>};
			my $perms = $teachers{$_}->{"permissions"};
			push @tas_js_hash_bts, qq!{name: "$ta_name", permissions: "$perms"}!;
	
		}

		my $select = qq{<SELECT style="width: 400px; height: 20px; position: absolute; border: none; margin: 0; font-size: 14px"  id="teachers" onclick="get_selected_teacher()">$options</SELECT>};
		
		$issued_to_field =
qq{
'<TD><LABEL for="issued_to" style="font-weight: bold"><span id="issued_to_asterisk" style="color: red"></span>Issued to</LABEL><TD style="position: absolute; margin: 0; width: 400px; height: 20px; border: solid black 1px"><span style="width: 400px; height: 18px; border: none">$select<INPUT type="text" name="issued_to" value="" style="width: 385px; height: 18px; position: absolute; border: none; font-size: 14px" id="issued_to" onchange="issued_to_changed()"></span><br>'
};

	}

	my $tas_js_hash = '[' . join(", ", @tas_js_hash_bts) .']';
	my $add_new_content =
 qq{
	'<div id="error" style="color: red"></div>' +
	'<TABLE cellspacing="10%">' +
	'<TR>' + $issued_to_field +

	'<TR><TD><LABEL for="expires_in" style="font-weight: bold"><span id="expires_in_asterisk" style="color: red"></span>Expires in</LABEL><TD><SELECT name="expires_in" id="expires_in" onchange="expires_in_changed()"><OPTION value="1">1 day</OPTION><OPTION value="2" selected>2 days</OPTION><OPTION value="3">3 days</OPTION></SELECT>' +	

	'<TR><TD><span id="privileges_asterisk" style="color: red"></span><LABEL style="font-weight: bold; text-decoration: underline">Privileges</LABEL><TD>' +

	'<TR><TD><LABEL style="font-weight: bold">Create Student Roll</LABEL><TD><INPUT type="checkbox" name="csr_check" id="csr_check" value="csr_check">' +};

	my @esr_ids_array = ();
	my @cm_ids_array  = ();
	my @em_ids_array  = ();
	my @vm_ids_array  = ();
	my @grc_ids_array = ();
	
	my $esr_code = qq{};
	my $cm_code  = qq{};
	my $em_code  = qq{};
	my $vm_code  = qq{};
	my $grc_code = qq{};

	my $esr_cntr = 0;
	my $cm_cntr  = 0;	

	for my $class (@classes) {
		++$esr_cntr;	
		push @esr_ids_array, qq{"esr_$class"};	
		push @vm_ids_array,  qq{"vm_$class"};
		push @grc_ids_array, qq{"grc_$class"};

		#First elem on list has no preceding spaces;
		if ($esr_cntr ==  1) {
			$esr_code .= qq{'<INPUT type="checkbox" name="esr_$class" value="esr_$class" id="esr_$class"><LABEL>$class</LABEL>' +};	
			$vm_code .= qq{'<INPUT type="checkbox" name="vm_$class" value="vm_$class" id="vm_$class"><LABEL>$class</LABEL>' +};	
			$grc_code .= qq{'<INPUT type="checkbox" name="grc_$class" value="grc_$class" id="grc_$class"><LABEL>$class</LABEL>' +};	
		}
		#Subsequent elems have preceding spaces;
		else {
			#5th element followed by a linebreak;
			if ($esr_cntr % 5 == 0) {
				$esr_code .= qq{'&nbsp;&nbsp;<INPUT type="checkbox" name="esr_$class" value="esr_$class" id="esr_$class"><LABEL>$class</LABEL><BR>' +};
				$vm_code .= qq{'&nbsp;&nbsp;<INPUT type="checkbox" name="vm_$class" value="vm_$class" id="vm_$class"><LABEL>$class</LABEL><BR>' +};
				$grc_code .= qq{'&nbsp;&nbsp;<INPUT type="checkbox" name="grc_$class" value="grc_$class" id="grc_$class"><LABEL>$class</LABEL><BR>' +};	
			}
			elsif ($esr_cntr % 6 == 0) {
				$esr_code .= qq{'<INPUT type="checkbox" name="esr_$class" value="esr_$class" id="esr_$class"><LABEL>$class</LABEL>' +};
				$vm_code  .= qq{'<INPUT type="checkbox" name="vm_$class" value="vm_$class" id="vm_$class"><LABEL>$class</LABEL>' +};
				$grc_code  .= qq{'<INPUT type="checkbox" name="grc_$class" value="grc_$class" id="grc_$class"><LABEL>$class</LABEL>' +};
			}
			else {
				$esr_code .= qq{'&nbsp;&nbsp;<INPUT type="checkbox" name="esr_$class" value="esr_$class" id="esr_$class"><LABEL>$class</LABEL>' +};
				$vm_code .= qq{'&nbsp;&nbsp;<INPUT type="checkbox" name="vm_$class" value="vm_$class" id="vm_$class"><LABEL>$class</LABEL>' +};
				$grc_code .= qq{'&nbsp;&nbsp;<INPUT type="checkbox" name="grc_$class" value="grc_$class" id="grc_$class"><LABEL>$class</LABEL>' +};	
			}
		}
	}

	for my $subject (@subjects) {
		for my $class (@classes) {

			++$cm_cntr;
	
			push @cm_ids_array, qq{"cm_$subject} . qq{_$class"};
			push @em_ids_array, qq{"em_$subject} . qq{_$class"};

			#First elem on list has no preceding spaces;
			if ($cm_cntr ==  1) {
				$cm_code .= qq{'<INPUT type="checkbox" name="cm_$subject} . qq{_$class" value="cm_$subject} . qq{_$class" id="cm_$subject} . qq{_$class"><LABEL>$subject $class</LABEL><BR>' +};
				$em_code .= qq{'<INPUT type="checkbox" name="em_$subject} . qq{_$class" value="em_$subject} . qq{_$class" id="em_$subject} . qq{_$class"><LABEL>$subject $class</LABEL><BR>' +};
			}
			#Subsequent elems have preceding spaces/linebreaks;
			else {
				#5th element followed by a linebreak;
				$cm_code .= qq{'<INPUT type="checkbox" name="cm_$subject} . qq{_$class" value="cm_$subject} . qq{_$class" id="cm_$subject} . qq{_$class"><LABEL>$subject $class</LABEL><BR>' +};
 				$em_code .= qq{'<INPUT type="checkbox" name="em_$subject} . qq{_$class" value="em_$subject} . qq{_$class" id="em_$subject} . qq{_$class"><LABEL>$subject $class</LABEL><BR>' +}; 
			}
		}
	}

	#limit height of the esr component to 100px max or
	#or the bare min height necessary

	my $esr_height = 24 * (int($esr_cntr / 5) + 1);
	
	$esr_height = 100 if ($esr_height > 100);
	$esr_height .= "px";
	$add_new_content .= 

qq{'<TR><TD><LABEL style="font-weight: bold">Edit Student Roll</LABEL><TD><div style="border: 1px solid; overflow-y: scroll; height: $esr_height">' +};
	$add_new_content .= $esr_code;
	$add_new_content .= qq{'</div>' +};

	$add_new_content .=
qq{'<TR><TD><LABEL style="font-weight: bold">Create Marksheet</LABEL><TD><div style="border: 1px solid; overflow-y: scroll; height: 100px">' +};
	$add_new_content .= $cm_code;

	$add_new_content .=
qq{'<TR><TD><LABEL style="font-weight: bold">Edit Marksheet</LABEL><TD><div style="border: 1px solid; overflow-y: scroll; height: 100px">' +};
	$add_new_content .= $em_code;

	$add_new_content .=
qq{'<TR><TD><LABEL style="font-weight: bold">View Class Marksheet</LABEL><TD><div style="border: 1px solid; overflow-y: scroll; height: $esr_height">' +};
	$add_new_content .= $vm_code;

	$add_new_content .=
qq{'<TR><TD><LABEL style="font-weight: bold">Generate Report Cards</LABEL><TD><div style="border: 1px solid; overflow-y: scroll; height: $esr_height">' +};
	$add_new_content .= $grc_code;

	my $esr_ids_string = '[' . join(', ', @esr_ids_array) . ']'; 
	my $cm_ids_string = '[' . join( ', ', @cm_ids_array) . ']';
	my $em_ids_string = '[' . join( ', ', @em_ids_array) . ']';
	my $vm_ids_string = '[' . join(', ', @vm_ids_array) . ']'; 
	my $grc_ids_string = '[' . join(', ', @grc_ids_array) . ']';
 
	$add_new_content .=
		qq{'<TR><TD><INPUT type="button" name="save_token" value="Save" onclick="verify_token()"><TD>' + 
		'<TR><TD colspan="2"><span id="err_log"></span>' +
		'</TABLE>'};

	
	my $content = 
'<!DOCTYPE html>
<html lang="en">
<head>
<title>Spanj :: Exam Management Information System :: Manage Tokens </title>
<script type="text/javascript">
	var esr_ids = ' . $esr_ids_string . ';
	var cm_ids  = ' . $cm_ids_string  . ';
	var em_ids  = ' . $em_ids_string  . ';
	var vm_ids  = ' . $vm_ids_string  . ';
	var grc_ids = ' . $grc_ids_string . ';
	var privs = new Array();
	var expired = ' . $expired_tokens . ';
	var selected = new Array();
	var all_tokens = ' .$all_tokens_var . ';

	var prev_ta_selection = "";
	var tas = ' . $tas_js_hash . ';

	function customize_sort_description() {
		var expiry_description =
					 "<SELECT name=\"sort_order\">" +
						"<OPTION value=\"0\">Farthest from expiry first</OPTION>" +
						"<OPTION value=\"1\">Closest to expiry first</OPTION>" +
					 "</SELECT>";

		var issued_to_description =
					 "<SELECT name=\"sort_order\">" +
						"<OPTION value=\"0\">Alphabetical order(Z-A)</OPTION>" +
						"<OPTION value=\"1\">Alphabetical order(A-Z)</OPTION>" +
					"</SELECT>";
		var privileges_description =
					"<SELECT name=\"sort_order\">" +
						"<OPTION value=\"0\">Most - least privileges</OPTION>" +
						"<OPTION value=\"1\">Least - most privileges</OPTION>" +
					"</SELECT>";

		var new_description = expiry_description;
		var selected_sort_by = document.getElementById("sort_by").value.toLowerCase();
		
		switch (selected_sort_by) {
			case "issued_to":
				new_description = issued_to_description;
				break;

			case "privileges":
				new_description = privileges_description;
		}
		
		document.getElementById("sort_order_container").innerHTML = new_description;
	}

	function check_expired() {
		document.getElementById("del_expired").disabled = true;
		if (expired.length > 0) {
			document.getElementById("del_expired").disabled = false;
		} 
	}

	function check_all() {
		var all_checked = document.getElementById("select_all").checked;
		if (all_checked) {
			selected = all_tokens;
			document.getElementById("del").disabled = false;
			document.getElementById("extend").disabled = false;
		}
		else {
			selected = [];
			document.getElementById("del").disabled = true;
			document.getElementById("extend").disabled = true;
		}

		for (var i = 0; i < all_tokens.length; i++) {
			document.getElementById(all_tokens[i].token).checked = all_checked;
		}
	}

	function del_expired() {
		if (expired.length > 0) {	
			var new_content = "<em>Are you sure you want to delete the following expired tokens?</em>";
			if (expired.length === 1) {
				new_content = "<em>Are you sure you want to delete the following expired token?</em>";
			}
			new_content += "<form method=\"post\" action=\"/cgi-bin/managetokens.cgi?pg='. $page . $mode_str .'\">";
			new_content += "<table cellspacing=\"10%\" border=\"1\"";
			new_content += "<thead><th>Token<th>Issued to</thead>";
			new_content += "<tbody>";
			for (var i = 0; i < expired.length; i++) {
				new_content += "<tr><td>" + expired[i].token + "<td>" + expired[i].issued_to;
				new_content += "<input type=\"hidden\" name=\"expired_" + expired[i].token + "\" value=\"" + expired[i].token + "\">";
			}
			new_content += "</table><br>";
			new_content += "<input type=\"hidden\" name=\"confirm_code\" value=\"'.$conf_code . '\">";
			new_content += "<input type=\"submit\" name=\"del_expired\" value=\"Confirm\">";
			new_content += "<input type=\"button\" name=\"cancel\" value=\"Cancel\" onclick=\"cancel_change()\">";
			new_content += "</form>";  
			document.getElementById("pre_conf").innerHTML = new_content;
		}
		else {
			alert ("You have no expired tokens on this page to delete!");
		}
	} 

	function cancel_change() {
		window.location.href = "/cgi-bin/managetokens.cgi?pg='. $page .$mode_str.'";
	}

	function check_token(sup_token, sup_issued_to) {	
		if (document.getElementById(sup_token) != null) {
			if (document.getElementById(sup_token).checked) {
				selected.push({token: sup_token, issued_to: sup_issued_to});	
				document.getElementById("del").disabled = false;
				document.getElementById("extend").disabled = false;
			}
			else {	
				for (var i = 0; i < selected.length; i++) {
					if (selected[i].token === sup_token) {
						selected.splice(i, 1);
						break;
					}
				}
				if (selected.length == 0) {
					document.getElementById("del").disabled = true;
					document.getElementById("extend").disabled = true;
				}
			}
		}
	}

	function extend_lease() {
		var select_options = "<OPTION selected value=\"1\">1 day</OPTION><OPTION value=\"2\">2 days</OPTION><OPTION value=\"3\">3 days</OPTION>";
		var new_content = "<em>Clicking \'confirm\' will set the following tokens to expire in the days specified</em>";

		if (selected.length == 1) {
			 new_content = "<em>Clicking \'confirm\' will set the following token to expire in the days specified</em>";
		}

		new_content += "<form method=\"post\" action=\"/cgi-bin/managetokens.cgi?pg='.$page.$mode_str.'\">";
		new_content += "<table cellpadding=\"10%\" border=\"1\"";
		new_content += "<thead><th>Token<th>Issued to<th>Will expire in</thead>";
		new_content += "<tbody>";
		
		for (var i = 0; i < selected.length; i++) {
			new_content += "<tr><td>" + selected[i].token + "<td>" + selected[i].issued_to + "<td><select name=\"extend_" + selected[i].token + "\">" + select_options + "</select>";	
		}
		new_content += "<tbody></table><br>";
		new_content += "<input type=\"hidden\" name=\"confirm_code\" value=\"'.$conf_code . '\">";
		new_content += "<input type=\"submit\" name=\"extend\" value=\"Confirm\">";
		new_content += "<input type=\"button\" name=\"cancel\" value=\"Cancel\" onclick=\"cancel_change()\">";
		new_content += "</form>";
		document.getElementById("pre_conf").innerHTML = new_content;
	}

	function del_selected() {	
		var new_content = "<em>Are you sure you want to delete the following tokens?</em><br>";
		if (selected.length == 1) {
			new_content = "<em>Are you sure you want to delete the following token?</em><br>";
		}	
		new_content += "<form method=\"post\" action=\"/cgi-bin/managetokens.cgi?pg='.$page.$mode_str.'\">";
		new_content += "<table cellpadding=\"10%\" border=\"1\"";
		new_content += "<thead><th>Token<th>Issued to</thead>";
		new_content += "<tbody>";
		for (var i = 0; i < selected.length; i++) {
			new_content += "<tr><td>" + selected[i].token + "<td>" + selected[i].issued_to;
			new_content += "<input type=\"hidden\" name=\"delete_" + selected[i].token + "\" value=\"" + selected[i].token + "\">";
		}
		new_content += "<tbody></table><br>";
		new_content += "<input type=\"hidden\" name=\"confirm_code\" value=\"'.$conf_code . '\">";
		new_content += "<input type=\"submit\" name=\"delete\" value=\"Confirm\">";
		new_content += "<input type=\"button\" name=\"cancel\" value=\"Cancel\" onclick=\"cancel_change()\">";
		new_content += "</form>";
		document.getElementById("pre_conf").innerHTML = new_content;

	}

	function add_new() {
		document.getElementById("pre_conf").style.border = "2px solid black";
		document.getElementById("pre_conf").style.width = "600px";	
		document.getElementById("pre_conf").style.padding = "2%";	
		document.getElementById("pre_conf").style.fontSize = "12px";
		var new_content = ' . $add_new_content . ';
		document.getElementById("pre_conf").innerHTML = new_content;
	}

	function verify_token() {
		document.getElementById("error").innerHTML += "<TABLE>";	
		if (document.getElementById("issued_to").value != "") {	
			if (document.getElementById("expires_in").value.match(/^[1-3]$/)) {	
				
				if (document.getElementById("csr_check").checked) {
					privs.push({title: "Create Student Roll", name: "csr", value: "*"}); 
				}
				add_checked(esr_ids, "esr", "Edit Student Roll");
				add_checked(cm_ids, "cm", "Create Marksheet");
				add_checked(em_ids, "em", "Edit Marksheet");
				add_checked(vm_ids, "vm", "View Class Marksheet");
				add_checked(grc_ids, "grc", "Generate Report Cards");	
	
				var u_friendly_privileges = "<NONE>";

				if (privs.length > 0) {
					for (var i = 0; i < privs.length; i++) {
						u_friendly_privileges += privs[i].title + "(" + privs[i].value + ")<BR>";
					}

					var conf_content = "";
					conf_content += "<em>Are you sure you want to add the following token to the system?</em><BR>";
					conf_content += "<table border=\"1\" cellpadding=\"5%\">";
					conf_content += "<thead><th>Issued to<th>Expires in<th>Privileges";
					conf_content += "<tbody><td>";
					conf_content += document.getElementById("issued_to").value;
					conf_content += "<td>" +  document.getElementById("expires_in").value + " days";
					conf_content += "<td>" + u_friendly_privileges;	
					conf_content += "</table>";
					conf_content += "<form method=\"POST\" action=\"/cgi-bin/managetokens.cgi?pg=' . $page . '\"><table cellpadding=\"2%\">";
					conf_content += "<input type=\"hidden\" name=\"confirm_code\" value=\"' . $conf_code . '\">";
					conf_content += "<input type=\"hidden\" name=\"issued_to\" value=\"" +  document.getElementById("issued_to").value + "\">";
					conf_content += "<input type=\"hidden\" name=\"expires_in\" value=\"" +  document.getElementById("expires_in").value + "\">";
					for (var i = 0; i < privs.length; i++) {
						conf_content += "<input type=\"hidden\" name=\"" + privs[i].name + "\" value=\"" + privs[i].value + "\">";
					}
					conf_content += "<tr><td><input type=\"submit\" name=\"add_new\" value=\"Confirm\">";
					conf_content += "<td><input type=\"button\" name=\"cancel\" value=\"Cancel\" onclick=\"cancel_change()\">";
					conf_content += "</table>";
					conf_content += "</form>";
					document.getElementById("pre_conf").style.fontSize = "14px";
					document.getElementById("pre_conf").innerHTML = conf_content;
				}

				else {
					document.getElementById("error").innerHTML += "<TR><TD>You have not set the privileges of the token";
					document.getElementById("privileges_asterisk").innerHTML = "* ";
				}
			}
			else {
				document.getElementById("error").innerHTML += "<TR><TD>The valid duration of a token\'s life is 1-3 days";
				document.getElementById("expires_in_asterisk").innerHTML = "* ";
			}
		}
		else {	
			document.getElementById("error").innerHTML += "<TR><TD>You must provide the name of the person to whom this token is issued";
			document.getElementById("issued_to_asterisk").innerHTML = "* ";
		}
		document.getElementById("error").innerHTML += "</TABLE>";
	}

	function add_checked(ids_list, form_name, title) {

		var checked = new Array();

		for (var i = 0; i < ids_list.length; i++) {
			document.getElementById("err_log").innerHTML += ids_list[i] + "&nbsp;&nbsp;";
			if (document.getElementById(ids_list[i]).checked) {
				var bts = ids_list[i].split("_");
				if (bts.length == 2) {
					checked.push(bts[1]);
				}
				else if(bts.length == 3) {
					checked.push(bts[2] + " " + bts[1]);
				}	
			}	
		}
		document.getElementById("err_log").innerHTML += "<BR>";
		if (checked.length > 0) {
			privs.push({title: title, name: form_name, value: checked.join(",")}); 
		}
	}

	function issued_to_changed() {
		if (document.getElementById("issued_to").value != "") {
			document.getElementById("error").innerHTML = "";
			document.getElementById("issued_to_asterisk").innerHTML = "";
		}
	}

	function expires_in_changed() {
		if (document.getElementById("expires_in").value.match(/[1-3]/)) {
			document.getElementById("error").innerHTML = "";
			document.getElementById("expires_in_asterisk").innerHTML = "";
		}
	}

	function get_selected_teacher() {
		var selection = document.getElementById("teachers").value;
		document.getElementById("issued_to").value = selection;

		for (var i = 0; i < tas.length; i++) {
			if (tas[i].name == prev_ta_selection) {
				var perms = (tas[i].permissions).split(",");
				for (var j = 0; j < perms.length; j++) {
					if ( document.getElementById(perms[j]) ) {
						document.getElementById(perms[j]).checked = false;
					}
				}
				break;
			}
		}

		for (var i = 0; i < tas.length; i++) {
			
			if (tas[i].name == selection) {
				prev_ta_selection = selection;

				var perms = (tas[i].permissions).split(",");
				for (var j = 0; j < perms.length; j++) {
					if ( document.getElementById(perms[j]) ) {
						document.getElementById(perms[j]).checked = true;
					}
				}
				break;
			}
		}
	}

</script>
<title>Spanj: Exam Management Information System - Manage Tokens</title>

</head>

<body onload="check_expired()">

<iframe width="30%" height=80 frameborder="1" src="/welcome2.html">
		<h5>Welcome to the </br>Spanj Exam Management Information System</h5>
	</iframe>
	<iframe width="20%" height=80 frameborder="1" src="/cgi-bin/check_login.cgi?cont=/settings.html">

	</iframe>
	<p><a href="/">Home</a> --&gt; <a href="/administrator.html">Administrator Panel</a> --&gt; <a href="/cgi-bin/managetokens.cgi">Manage Access Tokens</a>
	
	<hr><div id="pre_conf">'. 
	$per_page_guide . 
	$sort_guide . $search_bar .
	'<hr><p><input type="button" name="add_new" value="Add New Token" onclick="add_new()">' .
	qq{<p>$add_token_feedback} .
	$tokens_table .
'<br><table cellspacing="10%"><tr>
<td><input disabled type="button" name="del_selected" id="del" value="Delete Selected" onclick="del_selected()">
<td><input disabled type="button" name="extend_lease" id="extend" value="Extend Lease of Selected" onclick="extend_lease()">
<td><input type="button" name="del_expired" id="del_expired" value="Delete Expired" onclick="del_expired()">
</table>
';

	if ($cntr > 10) {
		$content .= "<br>$search_bar";
	}

	$content .= $page_guide . 
	'</div></body>
	</html>
	';

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
	print "Cache-Control: no-cache\r\n";
	print "\r\n";
	print $content;
}

else {

	print "Status: 302 Moved Temporarily\r\n";
	print "Location: /login.html?cont=/cgi-bin/managetokens.cgi\r\n";
	print "Content-Type: text/html; charset=ISO-8859-1\r\n";
       	my $res = 
               	"<html>
               	<head>
		<title>Spanj: Exam Management Information System - Redirect Failed</title>
		</head>
         	<body>
                You should have been redirected to <a href=\"/login.html?cont=/cgi-bin/managetokens.cgi\">/login.html?cont=/cgi-bin/managetokens.cgi</a>. If you were not, <a href=\"/cgi-bin/managetokens.cgi\">Click Here</a> 
		</body>
                </html>";

	my $content_len = length($res);	
	print "Content-Length: $content_len\r\n";
	print "\r\n";
	print $res;
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
		@key_space = ("A","B","C","D","F","G","H","J","K","L","M","N","P","W","X","4","5","6","8","9");
		$len = 10 + int (rand 5);
	}
	my $token = "";
	for (my $i = 0; $i < $len; $i++) {
		$token .= $key_space[int(rand @key_space)];
	}
	return $token;
}
